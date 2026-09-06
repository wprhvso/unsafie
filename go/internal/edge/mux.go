package edge

import (
	"context"
	"encoding/binary"
	"errors"
	"io"
	"net"
	"sync"
	"sync/atomic"
	"time"

	"unsafie/internal/bufpool"
	"unsafie/internal/usp"
)

const (
	flushInterval  = 400 * time.Microsecond
	flushThreshold = 48 << 10
	writeBufSize   = 64 << 10
	readBufSize    = 64 << 10
	ackEvery       = 256 << 10

	MaxPad = usp.MaxPadding + 2
)

var (
	errNoUplink   = errors.New("edge: uplink is not attached")
	errReplayGone = errors.New("edge: the peer asked for bytes that already scrolled out")
	errGoaway     = errors.New("edge: the exit is going away")
)

type muxConfig struct {
	StreamWindow  int64
	SessionWindow int64
	ReplayBytes   int
	MaxStreams    int
	Padder        usp.Padder
	OnStats       func(map[uint16]uint64)
	OnFault       func(usp.Reason, usp.Addr)
	OnRTT         func(time.Duration, time.Duration)
	OnHello       func(usp.ServerHello)
	Local         net.Addr
	Remote        net.Addr
}

// Mux turns one session into many streams. Everything above it sees net.Conn;
// everything below it sees two independent half duplex byte streams that both
// come and go, because that is all a strict HTTP/1.1 hop is willing to be.
type Mux struct {
	cfg muxConfig

	localAddr  net.Addr
	remoteAddr net.Addr

	mu      sync.RWMutex
	streams map[uint16]*stream
	nextID  uint16
	fatal   error

	session    *credit
	peerStream int64

	wmu     sync.Mutex
	writer  *usp.Writer
	wready  chan struct{}
	replay  *ring
	upAcked atomic.Int64
	dirty   atomic.Bool

	downOff  atomic.Int64
	downAcks atomic.Int64

	pings   sync.Map
	skew    atomic.Int64
	rtt     atomic.Int64
	closed  atomic.Bool
	done    chan struct{}
	stopped chan struct{}
}

func newMux(cfg muxConfig) *Mux {
	m := &Mux{
		cfg:        cfg,
		localAddr:  cfg.Local,
		remoteAddr: cfg.Remote,
		streams:    make(map[uint16]*stream),
		nextID:     1,
		session:    newCredit(cfg.SessionWindow),
		peerStream: cfg.StreamWindow,
		wready:     make(chan struct{}),
		replay:     newRing(cfg.ReplayBytes),
		done:       make(chan struct{}),
		stopped:    make(chan struct{}),
	}
	go m.flusher()
	return m
}

func (m *Mux) Done() <-chan struct{} { return m.done }

func (m *Mux) Streams() int {
	m.mu.RLock()
	defer m.mu.RUnlock()
	return len(m.streams)
}

func (m *Mux) RTT() time.Duration { return time.Duration(m.rtt.Load()) }

func (m *Mux) Skew() time.Duration { return time.Duration(m.skew.Load()) }

func (m *Mux) UplinkAt() int64 { return m.upAcked.Load() }

func (m *Mux) DownlinkAt() int64 { return m.downOff.Load() }

func (m *Mux) Close(err error) {
	if m.closed.Swap(true) {
		return
	}
	m.mu.Lock()
	if m.fatal == nil {
		m.fatal = err
	}
	streams := make([]*stream, 0, len(m.streams))
	for _, s := range m.streams {
		streams = append(streams, s)
	}
	m.streams = map[uint16]*stream{}
	m.mu.Unlock()

	for _, s := range streams {
		s.finish(err)
	}
	m.session.close()
	close(m.done)
	close(m.stopped)
}

func (m *Mux) failure() error {
	m.mu.RLock()
	defer m.mu.RUnlock()
	if m.fatal != nil {
		return m.fatal
	}
	return ErrSessionGone
}

func (m *Mux) Open(ctx context.Context, target usp.Addr, udp bool) (net.Conn, error) {
	if m.closed.Load() {
		return nil, m.failure()
	}

	m.mu.Lock()
	if len(m.streams) >= m.cfg.MaxStreams {
		m.mu.Unlock()
		return nil, usp.ReasonTooManyStreams
	}
	id := uint16(0)
	for range m.cfg.MaxStreams + 1 {
		m.nextID++
		if m.nextID == 0 {
			m.nextID = 1
		}
		if _, busy := m.streams[m.nextID]; !busy {
			id = m.nextID
			break
		}
	}
	if id == 0 {
		m.mu.Unlock()
		return nil, usp.ReasonTooManyStreams
	}
	s := newStream(m, id, target, udp, m.cfg.StreamWindow, m.peerStream)
	m.streams[id] = s
	m.mu.Unlock()

	payload := make([]byte, 0, target.Size()+1)
	proto := byte(1)
	if udp {
		proto = 2
	}
	payload = append(payload, proto)
	payload = usp.AppendAddr(payload, target)

	flags := usp.FlagUrgent
	if udp {
		flags |= usp.FlagUDP
	}
	if err := m.write(&usp.Frame{Type: usp.TypeOpen, Flags: flags, Stream: id, Payload: payload}); err != nil {
		m.dropStream(id, usp.ReasonNone, false)
		s.finish(err)
		return nil, err
	}

	if ctx != nil {
		if deadline, ok := ctx.Deadline(); ok {
			_ = s.SetDeadline(deadline)
		}
	}
	if udp {
		return &packetStream{s}, nil
	}
	return s, nil
}

func (m *Mux) reserve(want int64, exact bool) (int64, error) {
	for {
		got, ok := m.session.take(want)
		if !ok {
			return 0, m.failure()
		}
		if got > 0 && (!exact || got == want) {
			return got, nil
		}
		if got > 0 {
			m.session.add(got)
		}
		select {
		case <-m.session.signal:
		case <-m.done:
			return 0, m.failure()
		case <-time.After(20 * time.Millisecond):
		}
	}
}

func (m *Mux) OpenStrict(ctx context.Context, target usp.Addr, udp bool) (net.Conn, error) {
	conn, err := m.Open(ctx, target, udp)
	if err != nil {
		return nil, err
	}

	var s *stream
	switch c := conn.(type) {
	case *stream:
		s = c
	case *packetStream:
		s = c.stream
	}

	var timeout <-chan time.Time
	if deadline, ok := ctx.Deadline(); ok {
		t := time.NewTimer(time.Until(deadline))
		defer t.Stop()
		timeout = t.C
	}
	if err := s.awaitOpen(timeout); err != nil {
		_ = conn.Close()
		return nil, err
	}
	return conn, nil
}

func (m *Mux) sendData(id uint16, p []byte, udp bool) (int, error) {
	n, err := m.reserve(int64(len(p)), udp)
	if err != nil {
		return 0, err
	}
	f := usp.Frame{Type: usp.TypeData, Stream: id, Payload: p[:n]}
	if udp {
		f.Flags |= usp.FlagUDP
	}
	if err := m.write(&f); err != nil {
		m.session.add(n)
		return 0, err
	}
	return int(n), nil
}

func (m *Mux) sendEOF(id uint16) error {
	return m.write(&usp.Frame{Type: usp.TypeEOF, Flags: usp.FlagFin | usp.FlagUrgent, Stream: id})
}

func (m *Mux) sendWindow(id uint16, credit uint32) {
	payload := binary.BigEndian.AppendUint32(nil, credit)
	m.writeNB(&usp.Frame{Type: usp.TypeWindow, Flags: usp.FlagUrgent, Stream: id, Payload: payload})
}

func (m *Mux) dropStream(id uint16, reason usp.Reason, reset bool) {
	m.mu.Lock()
	s := m.streams[id]
	delete(m.streams, id)
	m.mu.Unlock()

	if s == nil {
		return
	}
	s.rx.discard()
	if reset && !m.closed.Load() {
		m.writeNB(&usp.Frame{
			Type:    usp.TypeReset,
			Flags:   usp.FlagUrgent,
			Stream:  id,
			Payload: []byte{byte(reason)},
		})
	}
}

// writeNB is what the read loop and the flow control path use: a frame that
// cannot be handed to a live uplink right now is dropped rather than parked,
// because parking it would stall the very loop that has to notice the uplink
// coming back.
func (m *Mux) writeNB(f *usp.Frame) {
	m.wmu.Lock()
	defer m.wmu.Unlock()
	if m.writer == nil {
		return
	}
	if err := m.writer.WriteFrame(f); err != nil {
		m.writer = nil
		return
	}
	if err := m.writer.Flush(); err != nil {
		m.writer = nil
	}
}

func (m *Mux) write(f *usp.Frame) error {
	for {
		m.wmu.Lock()
		if m.writer != nil {
			err := m.writer.WriteFrame(f)
			if err == nil {
				m.dirty.Store(true)
				if f.Type.Control() || m.writer.Buffered() >= flushThreshold {
					err = m.writer.Flush()
					m.dirty.Store(false)
				}
			}
			if err != nil {
				m.writer = nil
			}
			m.wmu.Unlock()
			if err == nil {
				return nil
			}
			continue
		}
		ready := m.wready
		m.wmu.Unlock()

		select {
		case <-ready:
		case <-m.done:
			return m.failure()
		}
	}
}

func (m *Mux) flusher() {
	t := time.NewTicker(flushInterval)
	defer t.Stop()
	for {
		select {
		case <-m.stopped:
			return
		case <-t.C:
		}
		if !m.dirty.Load() {
			continue
		}
		m.wmu.Lock()
		if m.writer != nil {
			if err := m.writer.Flush(); err != nil {
				m.writer = nil
			}
			m.dirty.Store(false)
		}
		m.wmu.Unlock()
	}
}

// attachUp binds a fresh uplink body. Whatever the peer had not acknowledged is
// pushed again first, so the frame stream the exit parses is continuous even
// though the connection carrying it is not.
func (m *Mux) attachUp(w io.Writer) (int64, error) {
	from := m.upAcked.Load()
	backlog, ok := m.replay.Since(from)
	if !ok {
		return from, errReplayGone
	}

	writer := usp.NewWriter(w, writeBufSize, m.cfg.Padder)
	writer.SetTap(m.replay.Append)

	if len(backlog) > 0 {
		if _, err := w.Write(backlog); err != nil {
			return from, err
		}
	}

	m.wmu.Lock()
	m.writer = writer
	ready := m.wready
	m.wready = make(chan struct{})
	m.wmu.Unlock()
	close(ready)
	return from, nil
}

func (m *Mux) detachUp() {
	m.wmu.Lock()
	m.writer = nil
	m.wmu.Unlock()
}

func (m *Mux) attachDown(r io.Reader) error {
	reader := usp.NewReader(r, readBufSize)
	base := m.downOff.Load()
	scratch := bufpool.Chunks.Get()
	defer bufpool.Chunks.Put(scratch)

	buf := *scratch
	for {
		f, used, err := reader.ReadFrame(buf)
		if cap(used) == bufpool.ChunkSize {
			buf = used[:cap(used)]
		}
		if err != nil {
			m.downOff.Store(base + reader.Consumed())
			return err
		}
		m.downOff.Store(base + reader.Consumed())
		if err := m.dispatch(f); err != nil {
			return err
		}
		if m.downOff.Load()-m.downAcks.Load() >= ackEvery {
			m.downAcks.Store(m.downOff.Load())
			payload := binary.BigEndian.AppendUint64(nil, uint64(m.downOff.Load()))
			m.writeNB(&usp.Frame{Type: usp.TypeAck, Flags: usp.FlagUrgent, Payload: payload})
		}
	}
}

func (m *Mux) lookup(id uint16) *stream {
	m.mu.RLock()
	defer m.mu.RUnlock()
	return m.streams[id]
}

func (m *Mux) dispatch(f usp.Frame) error {
	switch f.Type {
	case usp.TypeData:
		s := m.lookup(f.Stream)
		if s == nil {
			m.creditBack(len(f.Payload))
			return nil
		}
		s.rx.push(f.Payload)
		return nil

	case usp.TypeOpenOK:
		if s := m.lookup(f.Stream); s != nil {
			s.markOpen(nil)
		}
		return nil

	case usp.TypeOpenErr:
		reason := usp.ReasonInternal
		detail := ""
		if len(f.Payload) > 0 {
			reason = usp.Reason(f.Payload[0])
			detail = string(f.Payload[1:])
		}
		s := m.lookup(f.Stream)
		if s == nil {
			return nil
		}
		if m.cfg.OnFault != nil {
			m.cfg.OnFault(reason, s.target)
		}
		var err error = &OpenError{Reason: reason, Detail: detail}
		m.dropStream(f.Stream, usp.ReasonNone, false)
		s.finish(err)
		return nil

	case usp.TypeEOF:
		if s := m.lookup(f.Stream); s != nil {
			s.rx.fail(io.EOF)
		}
		return nil

	case usp.TypeReset:
		reason := usp.ReasonNone
		if len(f.Payload) > 0 {
			reason = usp.Reason(f.Payload[0])
		}
		s := m.lookup(f.Stream)
		m.dropStream(f.Stream, usp.ReasonNone, false)
		if s != nil {
			if m.cfg.OnFault != nil && reason != usp.ReasonNone {
				m.cfg.OnFault(reason, s.target)
			}
			s.finish(streamError(reason))
		}
		return nil

	case usp.TypeWindow:
		if len(f.Payload) < 4 {
			return usp.ErrBadFrame
		}
		credit := int64(binary.BigEndian.Uint32(f.Payload))
		if f.Stream == 0 {
			m.session.add(credit)
			return nil
		}
		if s := m.lookup(f.Stream); s != nil {
			s.tx.add(credit)
		}
		return nil

	case usp.TypeAck:
		if len(f.Payload) >= 8 {
			m.upAcked.Store(int64(binary.BigEndian.Uint64(f.Payload)))
		}
		return nil

	case usp.TypePing:
		echo := append(append([]byte(nil), f.Payload...), binary.BigEndian.AppendUint64(nil, uint64(time.Now().UnixMicro()))...)
		m.writeNB(&usp.Frame{Type: usp.TypePong, Flags: usp.FlagUrgent, Payload: echo})
		return nil

	case usp.TypePong:
		m.completePing(f.Payload)
		return nil

	case usp.TypeStats:
		if m.cfg.OnStats != nil {
			m.cfg.OnStats(decodeStats(f.Payload))
		}
		return nil

	case usp.TypeGoaway:
		return errGoaway

	case usp.TypeHelloAck:
		hello, err := usp.DecodeServerHello(f.Payload)
		if err != nil {
			return err
		}
		m.applyHello(hello)
		if m.cfg.OnHello != nil {
			m.cfg.OnHello(hello)
		}
		return nil

	case usp.TypeSettings:
		return nil

	default:
		return nil
	}
}

// seed puts a frame at offset zero of the uplink without a leg to write it to.
// The replay ring is what a fresh leg sends first, so a frame seeded before the
// session has any connection at all is simply the first thing the exit reads —
// which is how the hello travels without a round trip of its own.
func (m *Mux) seed(f *usp.Frame) {
	buf := make([]byte, usp.HeaderSize+len(f.Payload))
	usp.PutHeader(buf, f.Type, f.Flags, f.Stream, len(f.Payload))
	copy(buf[usp.HeaderSize:], f.Payload)
	m.replay.Append(buf)
}

// applyHello adjusts the credit the client is allowed to spend once the exit
// says what it will accept. Streams opened before the answer arrived started on
// the shared default, so they are corrected by the difference rather than reset.
func (m *Mux) applyHello(h usp.ServerHello) {
	if h.SessionWindow > 0 {
		if delta := int64(h.SessionWindow) - m.cfg.SessionWindow; delta != 0 {
			m.cfg.SessionWindow = int64(h.SessionWindow)
			m.session.add(delta)
		}
	}
	if h.StreamWindow == 0 {
		return
	}

	m.mu.Lock()
	delta := int64(h.StreamWindow) - m.peerStream
	m.peerStream = int64(h.StreamWindow)
	streams := make([]*stream, 0, len(m.streams))
	for _, s := range m.streams {
		streams = append(streams, s)
	}
	m.mu.Unlock()

	if delta == 0 {
		return
	}
	for _, s := range streams {
		s.tx.add(delta)
	}
}

func (m *Mux) creditBack(n int) {
	if n > 0 {
		m.sendWindow(0, uint32(n))
	}
}

func streamError(r usp.Reason) error {
	switch r {
	case usp.ReasonNone, usp.ReasonIdle:
		return io.EOF
	default:
		return &OpenError{Reason: r}
	}
}

func (m *Mux) Ping(ctx context.Context) (time.Duration, error) {
	token := uint64(time.Now().UnixNano())
	reply := make(chan time.Duration, 1)
	m.pings.Store(token, reply)
	defer m.pings.Delete(token)

	payload := binary.BigEndian.AppendUint64(nil, token)
	payload = binary.BigEndian.AppendUint64(payload, uint64(time.Now().UnixMicro()))
	sent := time.Now()
	if err := m.write(&usp.Frame{Type: usp.TypePing, Flags: usp.FlagUrgent, Payload: payload}); err != nil {
		return 0, err
	}

	select {
	case <-reply:
		return time.Since(sent), nil
	case <-ctx.Done():
		return 0, ctx.Err()
	case <-m.done:
		return 0, m.failure()
	}
}

func (m *Mux) completePing(payload []byte) {
	if len(payload) < 16 {
		return
	}
	token := binary.BigEndian.Uint64(payload)
	sentAt := int64(binary.BigEndian.Uint64(payload[8:]))
	rtt := time.Duration(time.Now().UnixMicro()-sentAt) * time.Microsecond
	if rtt > 0 {
		m.rtt.Store(int64(rtt))
	}
	if len(payload) >= 24 {
		remote := int64(binary.BigEndian.Uint64(payload[16:]))
		mid := sentAt + rtt.Microseconds()/2
		m.skew.Store((remote - mid) * int64(time.Microsecond))
	}
	if ch, ok := m.pings.LoadAndDelete(token); ok {
		select {
		case ch.(chan time.Duration) <- rtt:
		default:
		}
	}
	if m.cfg.OnRTT != nil {
		m.cfg.OnRTT(rtt, time.Duration(m.skew.Load()))
	}
}

func decodeStats(p []byte) map[uint16]uint64 {
	out := make(map[uint16]uint64, len(p)/10)
	for len(p) >= 10 {
		out[binary.BigEndian.Uint16(p)] = binary.BigEndian.Uint64(p[2:])
		p = p[10:]
	}
	return out
}
