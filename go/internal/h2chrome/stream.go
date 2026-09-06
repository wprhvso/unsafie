package h2chrome

import (
	"errors"
	"io"
	"net/http"
	"sync"

	"golang.org/x/net/http2"
)

type clientStream struct {
	cc  *clientConn
	id  uint32
	req *http.Request

	body *bodyReader
	resp chan *http.Response
	done chan struct{}

	once        sync.Once
	err         error
	gotResponse bool

	sendWindow int32
	flow       chan struct{}
}

func newClientStream(cc *clientConn, id uint32, req *http.Request) *clientStream {
	cs := &clientStream{
		cc:         cc,
		id:         id,
		req:        req,
		resp:       make(chan *http.Response, 1),
		done:       make(chan struct{}),
		flow:       make(chan struct{}, 1),
		sendWindow: cc.peerInitial,
	}
	cs.body = &bodyReader{cs: cs, signal: make(chan struct{}, 1)}
	return cs
}

func (cs *clientStream) deliver(resp *http.Response) {
	select {
	case cs.resp <- resp:
	default:
	}
}

func (cs *clientStream) fail(err error) {
	cs.once.Do(func() {
		if err == nil {
			err = errClosed
		}
		cs.err = err
		close(cs.done)
		cs.body.close(err)
	})
}

func (cs *clientStream) failure() error {
	select {
	case <-cs.done:
		return cs.err
	default:
		return nil
	}
}

func (cs *clientStream) wake() {
	select {
	case cs.flow <- struct{}{}:
	default:
	}
}

func (cs *clientStream) addWindow(delta int32) {
	cs.cc.mu.Lock()
	cs.sendWindow += delta
	cs.cc.mu.Unlock()
	cs.wake()
}

// cancel is what a context deadline turns into on the wire. Dropping the
// stream without telling the peer would leave it writing into a window nobody
// will ever return.
func (cs *clientStream) cancel() {
	cs.cc.drop(cs.id)
	_ = cs.cc.frame(func() error { return cs.cc.fr.WriteRSTStream(cs.id, http2.ErrCodeCancel) })
	cs.fail(errors.New("h2chrome: stream cancelled"))
}

func (cs *clientStream) reserve(want int) (int, error) {
	cc := cs.cc
	for {
		cc.mu.Lock()
		if cc.err != nil {
			err := cc.err
			cc.mu.Unlock()
			return 0, err
		}
		available := cs.sendWindow
		if cc.connSend < available {
			available = cc.connSend
		}
		frame := int32(cc.peerFrameSize)
		if available > 0 {
			n := int32(want)
			if n > available {
				n = available
			}
			if n > frame {
				n = frame
			}
			cs.sendWindow -= n
			cc.connSend -= n
			cc.mu.Unlock()
			return int(n), nil
		}
		cc.mu.Unlock()

		select {
		case <-cs.flow:
		case <-cs.done:
			return 0, cs.failure()
		case <-cc.closed:
			return 0, errClosed
		case <-cs.req.Context().Done():
			return 0, cs.req.Context().Err()
		}
	}
}

func (cs *clientStream) writeData(data []byte, endStream bool) error {
	cc := cs.cc

	if len(data) == 0 {
		if !endStream {
			return nil
		}
		return cc.frame(func() error { return cc.fr.WriteData(cs.id, true, nil) })
	}

	for len(data) > 0 {
		n, err := cs.reserve(len(data))
		if err != nil {
			return err
		}
		chunk := data[:n]
		data = data[n:]
		last := endStream && len(data) == 0
		if err := cc.frame(func() error { return cc.fr.WriteData(cs.id, last, chunk) }); err != nil {
			return err
		}
	}
	return nil
}

func (cs *clientStream) writeBody(body io.ReadCloser) {
	defer body.Close()

	buf := make([]byte, defaultPeerFrameSize)
	for {
		n, err := body.Read(buf)
		if n > 0 {
			if werr := cs.writeData(buf[:n], false); werr != nil {
				cs.fail(werr)
				return
			}
		}
		if err == nil {
			continue
		}
		if errors.Is(err, io.EOF) {
			if werr := cs.writeData(nil, true); werr != nil {
				cs.fail(werr)
			}
			return
		}
		cs.cancel()
		return
	}
}

type bodyReader struct {
	cs *clientStream

	mu      sync.Mutex
	chunks  [][]byte
	size    int
	err     error
	closed  bool
	pending uint32
	signal  chan struct{}
}

func (b *bodyReader) wake() {
	select {
	case b.signal <- struct{}{}:
	default:
	}
}

func (b *bodyReader) push(p []byte) {
	chunk := make([]byte, len(p))
	copy(chunk, p)

	b.mu.Lock()
	if b.closed {
		b.mu.Unlock()
		return
	}
	b.chunks = append(b.chunks, chunk)
	b.size += len(chunk)
	b.mu.Unlock()
	b.wake()
}

func (b *bodyReader) close(err error) {
	b.mu.Lock()
	if b.err == nil {
		b.err = err
	}
	b.mu.Unlock()
	b.wake()
}

func (b *bodyReader) Read(p []byte) (int, error) {
	if len(p) == 0 {
		return 0, nil
	}

	for {
		b.mu.Lock()
		if len(b.chunks) > 0 {
			n := copy(p, b.chunks[0])
			b.chunks[0] = b.chunks[0][n:]
			if len(b.chunks[0]) == 0 {
				b.chunks = b.chunks[1:]
			}
			b.size -= n
			b.pending += uint32(n)
			credit := uint32(0)
			if b.pending >= b.cs.cc.t.profile().InitialWindowSize/2 {
				credit, b.pending = b.pending, 0
			}
			closed := b.closed
			b.mu.Unlock()

			if credit > 0 && !closed {
				b.cs.cc.creditStream(b.cs.id, credit)
			}
			return n, nil
		}
		err := b.err
		b.mu.Unlock()

		if err != nil {
			return 0, err
		}

		select {
		case <-b.signal:
		case <-b.cs.done:
		case <-b.cs.req.Context().Done():
			return 0, b.cs.req.Context().Err()
		}
	}
}

func (b *bodyReader) Close() error {
	b.mu.Lock()
	already := b.closed
	b.closed = true
	unread := b.err == nil
	b.chunks, b.size = nil, 0
	if b.err == nil {
		b.err = errClosed
	}
	b.mu.Unlock()

	if !already && unread {
		b.cs.cancel()
	}
	b.wake()
	return nil
}
