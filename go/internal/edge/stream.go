package edge

import (
	"errors"
	"io"
	"net"
	"os"
	"sync"
	"sync/atomic"
	"time"

	"unsafie/internal/usp"
)

var (
	ErrStreamReset  = errors.New("edge: stream reset by the exit")
	ErrSessionGone  = errors.New("edge: session is gone")
	ErrOpenRejected = errors.New("edge: the exit refused to open the stream")
)

type OpenError struct {
	Reason usp.Reason
	Detail string
}

func (e *OpenError) Error() string {
	if e.Detail == "" {
		return "edge: open refused: " + e.Reason.String()
	}
	return "edge: open refused: " + e.Reason.String() + ": " + e.Detail
}

func (e *OpenError) Is(target error) bool { return target == ErrOpenRejected }

func (e *OpenError) Blames() usp.Fault { return e.Reason.Blames() }

type stream struct {
	id  uint16
	mux *Mux

	target usp.Addr
	udp    bool

	rx     *recvBuf
	tx     *credit
	window int64

	pending  atomic.Int64
	opened   chan struct{}
	openErr  atomic.Pointer[error]
	openOnce sync.Once

	closeOnce  sync.Once
	finishOnce sync.Once
	done       chan struct{}

	writeMu sync.Mutex
	txDone  atomic.Bool

	deadlines struct {
		mu     sync.Mutex
		read   time.Time
		write  time.Time
		linger time.Duration
	}

	stats struct {
		in        atomic.Int64
		out       atomic.Int64
		openedAt  time.Time
		firstByte atomic.Int64
	}
}

func newStream(m *Mux, id uint16, target usp.Addr, udp bool, window int64) *stream {
	s := &stream{
		id:     id,
		mux:    m,
		target: target,
		udp:    udp,
		rx:     newRecvBuf(udp),
		tx:     newCredit(window),
		window: window,
		opened: make(chan struct{}),
		done:   make(chan struct{}),
	}
	s.stats.openedAt = time.Now()
	return s
}

func (s *stream) awaitOpen(deadline <-chan time.Time) error {
	select {
	case <-s.opened:
		if p := s.openErr.Load(); p != nil {
			return *p
		}
		return nil
	case <-s.done:
		return s.terminalError()
	case <-deadline:
		return os.ErrDeadlineExceeded
	}
}

func (s *stream) terminalError() error {
	if err := s.rx.failure(); err != nil {
		return err
	}
	return net.ErrClosed
}

func (s *stream) Read(p []byte) (int, error) {
	if len(p) == 0 {
		return 0, nil
	}
	for {
		if n := s.rx.pull(p); n > 0 {
			s.stats.in.Add(int64(n))
			s.stats.firstByte.CompareAndSwap(0, time.Since(s.stats.openedAt).Microseconds()+1)
			s.replenish(n)
			return n, nil
		}
		if err := s.rx.failure(); err != nil {
			return 0, err
		}

		timer, timeout := s.readTimer()
		select {
		case <-s.rx.signal:
		case <-timeout:
			return 0, os.ErrDeadlineExceeded
		case <-s.done:
			if n := s.rx.pull(p); n > 0 {
				s.stats.in.Add(int64(n))
				s.replenish(n)
				return n, nil
			}
			return 0, s.terminalError()
		}
		if timer != nil {
			timer.Stop()
		}
	}
}

func (s *stream) readTimer() (*time.Timer, <-chan time.Time) {
	s.deadlines.mu.Lock()
	deadline, idle := s.deadlines.read, s.deadlines.linger
	s.deadlines.mu.Unlock()

	if idle > 0 {
		if until := time.Now().Add(idle); deadline.IsZero() || until.Before(deadline) {
			deadline = until
		}
	}
	if deadline.IsZero() {
		return nil, nil
	}
	t := time.NewTimer(time.Until(deadline))
	return t, t.C
}

func (s *stream) replenish(n int) {
	if s.pending.Add(int64(n)) < s.window/2 {
		return
	}
	credit := s.pending.Swap(0)
	if credit <= 0 {
		return
	}
	s.mux.sendWindow(s.id, uint32(credit))
	s.mux.sendWindow(0, uint32(credit))
}

func (s *stream) awaitCredit() error {
	timer, timeout := s.writeTimer()
	if timer != nil {
		defer timer.Stop()
	}
	select {
	case <-s.tx.signal:
		return nil
	case <-timeout:
		return os.ErrDeadlineExceeded
	case <-s.done:
		return s.terminalError()
	}
}

func (s *stream) Write(p []byte) (int, error) {
	s.writeMu.Lock()
	defer s.writeMu.Unlock()

	if s.txDone.Load() {
		return 0, net.ErrClosed
	}
	if s.udp {
		return s.writeDatagram(p)
	}

	written := 0
	for written < len(p) {
		if err := s.writable(); err != nil {
			return written, err
		}
		want, ok := s.tx.take(int64(min(len(p)-written, usp.DefaultChunk)))
		if !ok {
			return written, s.terminalError()
		}
		if want == 0 {
			if err := s.awaitCredit(); err != nil {
				return written, err
			}
			continue
		}
		sent, err := s.mux.sendData(s.id, p[written:written+int(want)], false)
		s.tx.add(want - int64(sent))
		written += sent
		s.stats.out.Add(int64(sent))
		if err != nil {
			return written, err
		}
	}
	return written, nil
}

var errDatagramTooLarge = errors.New("edge: datagram exceeds the maximum frame payload")

func (s *stream) writeDatagram(p []byte) (int, error) {
	if len(p) > usp.MaxPayload-MaxPad {
		return 0, errDatagramTooLarge
	}
	for {
		if err := s.writable(); err != nil {
			return 0, err
		}
		got, ok := s.tx.takeExact(int64(len(p)))
		if !ok {
			return 0, s.terminalError()
		}
		if got == 0 {
			if err := s.awaitCredit(); err != nil {
				return 0, err
			}
			continue
		}
		sent, err := s.mux.sendData(s.id, p, true)
		if err != nil {
			s.tx.add(int64(len(p)))
			return 0, err
		}
		s.stats.out.Add(int64(sent))
		return sent, nil
	}
}

func (s *stream) writable() error {
	select {
	case <-s.done:
		return s.terminalError()
	default:
	}
	s.deadlines.mu.Lock()
	deadline := s.deadlines.write
	s.deadlines.mu.Unlock()
	if !deadline.IsZero() && !time.Now().Before(deadline) {
		return os.ErrDeadlineExceeded
	}
	return nil
}

func (s *stream) writeTimer() (*time.Timer, <-chan time.Time) {
	s.deadlines.mu.Lock()
	deadline := s.deadlines.write
	s.deadlines.mu.Unlock()
	if deadline.IsZero() {
		return nil, nil
	}
	t := time.NewTimer(time.Until(deadline))
	return t, t.C
}

func (s *stream) CloseWrite() error {
	if s.txDone.Swap(true) {
		return nil
	}
	return s.mux.sendEOF(s.id)
}

func (s *stream) Close() error {
	s.closeOnce.Do(func() {
		s.mux.dropStream(s.id, usp.ReasonNone, !s.txDone.Load())
		s.finish(net.ErrClosed)
	})
	return nil
}

func (s *stream) markOpen(err error) {
	s.openOnce.Do(func() {
		if err != nil {
			s.openErr.Store(&err)
		}
		close(s.opened)
	})
}

func (s *stream) finish(err error) {
	s.finishOnce.Do(func() {
		s.rx.fail(err)
		s.tx.close()
		close(s.done)
		s.markOpen(err)
	})
}

func (s *stream) LocalAddr() net.Addr  { return s.mux.localAddr }
func (s *stream) RemoteAddr() net.Addr { return s.mux.remoteAddr }

func (s *stream) SetDeadline(t time.Time) error {
	s.deadlines.mu.Lock()
	s.deadlines.read, s.deadlines.write = t, t
	s.deadlines.mu.Unlock()
	s.rx.wake()
	return nil
}

func (s *stream) SetReadDeadline(t time.Time) error {
	s.deadlines.mu.Lock()
	s.deadlines.read = t
	s.deadlines.mu.Unlock()
	s.rx.wake()
	return nil
}

func (s *stream) SetWriteDeadline(t time.Time) error {
	s.deadlines.mu.Lock()
	s.deadlines.write = t
	s.deadlines.mu.Unlock()
	return nil
}

func (s *stream) SetReadLinger(d time.Duration) {
	s.deadlines.mu.Lock()
	s.deadlines.linger = d
	s.deadlines.mu.Unlock()
	s.rx.wake()
}

type packetStream struct{ *stream }

var _ net.PacketConn = (*packetStream)(nil)

func (p *packetStream) ReadFrom(b []byte) (int, net.Addr, error) {
	n, err := p.Read(b)
	return n, p.RemoteAddr(), err
}

func (p *packetStream) WriteTo(b []byte, _ net.Addr) (int, error) { return p.Write(b) }

var _ io.ReadWriteCloser = (*stream)(nil)
