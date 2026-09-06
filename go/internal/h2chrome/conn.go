package h2chrome

import (
	"bufio"
	"bytes"
	"errors"
	"fmt"
	"io"
	"net"
	"net/http"
	"strconv"
	"sync"
	"sync/atomic"
	"time"

	"golang.org/x/net/http2"
	"golang.org/x/net/http2/hpack"
)

const (
	defaultPeerWindow    = 65535
	defaultPeerFrameSize = 16384
	writeBufSize         = 32 << 10
	readBufSize          = 32 << 10
)

var (
	// ErrRetry means the request never made it onto the wire, so sending it
	// again on a fresh connection is safe even when it is not idempotent.
	ErrRetry = errors.New("h2chrome: connection went away before the request was written")

	errClosed      = errors.New("h2chrome: connection closed")
	errStreamReset = errors.New("h2chrome: stream reset by the peer")
	errFlowControl = errors.New("h2chrome: peer broke flow control")
)

type clientConn struct {
	t    *Transport
	conn net.Conn
	fr   *http2.Framer
	bw   *bufio.Writer

	wmu  sync.Mutex
	henc *hpack.Encoder
	hbuf bytes.Buffer

	mu            sync.Mutex
	streams       map[uint32]*clientStream
	nextID        uint32
	maxConcurrent uint32
	connSend      int32
	peerInitial   int32
	peerFrameSize uint32
	goingAway     bool
	err           error
	recvUnacked   uint32

	closed    chan struct{}
	closeOnce sync.Once
	lastUse   atomic.Int64
	inflight  atomic.Int32
}

func newClientConn(t *Transport, c net.Conn) (*clientConn, error) {
	profile := t.profile()

	cc := &clientConn{
		t:             t,
		conn:          c,
		bw:            bufio.NewWriterSize(c, writeBufSize),
		streams:       make(map[uint32]*clientStream),
		nextID:        1,
		maxConcurrent: 100,
		connSend:      defaultPeerWindow,
		peerInitial:   defaultPeerWindow,
		peerFrameSize: defaultPeerFrameSize,
		closed:        make(chan struct{}),
	}
	cc.fr = http2.NewFramer(cc.bw, bufio.NewReaderSize(c, readBufSize))
	cc.fr.ReadMetaHeaders = hpack.NewDecoder(profile.HeaderTableSize, nil)
	cc.fr.MaxHeaderListSize = profile.MaxHeaderListSize
	cc.fr.SetMaxReadFrameSize(profile.MaxFrameSize)
	cc.henc = hpack.NewEncoder(&cc.hbuf)
	cc.touch()

	// The preface, the settings and the connection window arrive as one write,
	// the way a browser sends them: a client that splits them across packets is
	// already unusual before it has said anything.
	cc.wmu.Lock()
	defer cc.wmu.Unlock()

	if _, err := cc.bw.WriteString(http2.ClientPreface); err != nil {
		return nil, err
	}
	if err := cc.fr.WriteSettings(profile.Settings...); err != nil {
		return nil, err
	}
	if profile.ConnectionWindow > 0 {
		if err := cc.fr.WriteWindowUpdate(0, profile.ConnectionWindow); err != nil {
			return nil, err
		}
	}
	if err := cc.bw.Flush(); err != nil {
		return nil, err
	}

	go cc.readLoop()
	return cc, nil
}

func (cc *clientConn) touch() { cc.lastUse.Store(time.Now().UnixNano()) }

func (cc *clientConn) idleFor() time.Duration {
	return time.Since(time.Unix(0, cc.lastUse.Load()))
}

func (cc *clientConn) usable() bool {
	cc.mu.Lock()
	defer cc.mu.Unlock()
	return cc.err == nil && !cc.goingAway && uint32(len(cc.streams)) < cc.maxConcurrent
}

func (cc *clientConn) closeWithError(err error) {
	cc.closeOnce.Do(func() {
		cc.mu.Lock()
		if cc.err == nil {
			cc.err = err
		}
		streams := make([]*clientStream, 0, len(cc.streams))
		for _, cs := range cc.streams {
			streams = append(streams, cs)
		}
		cc.streams = map[uint32]*clientStream{}
		cc.mu.Unlock()

		close(cc.closed)
		_ = cc.conn.Close()
		for _, cs := range streams {
			cs.fail(err)
		}
		cc.t.forget(cc)
	})
}

func (cc *clientConn) frame(fn func() error) error {
	cc.wmu.Lock()
	defer cc.wmu.Unlock()
	if err := fn(); err != nil {
		return err
	}
	return cc.bw.Flush()
}

func (cc *clientConn) readLoop() {
	for {
		f, err := cc.fr.ReadFrame()
		if err != nil {
			cc.closeWithError(err)
			return
		}
		if err := cc.dispatch(f); err != nil {
			cc.closeWithError(err)
			return
		}
	}
}

func (cc *clientConn) dispatch(f http2.Frame) error {
	switch f := f.(type) {
	case *http2.MetaHeadersFrame:
		cc.onHeaders(f)
	case *http2.DataFrame:
		return cc.onData(f)
	case *http2.RSTStreamFrame:
		if cs := cc.stream(f.StreamID); cs != nil {
			cc.drop(cs.id)
			cs.fail(fmt.Errorf("%w: %s", errStreamReset, f.ErrCode))
		}
	case *http2.SettingsFrame:
		return cc.onSettings(f)
	case *http2.WindowUpdateFrame:
		cc.onWindowUpdate(f)
	case *http2.PingFrame:
		if !f.IsAck() {
			return cc.frame(func() error { return cc.fr.WritePing(true, f.Data) })
		}
	case *http2.GoAwayFrame:
		cc.mu.Lock()
		cc.goingAway = true
		last := f.LastStreamID
		orphans := make([]*clientStream, 0)
		for id, cs := range cc.streams {
			if id > last {
				orphans = append(orphans, cs)
				delete(cc.streams, id)
			}
		}
		cc.mu.Unlock()
		for _, cs := range orphans {
			cs.fail(ErrRetry)
		}
	}
	return nil
}

func (cc *clientConn) stream(id uint32) *clientStream {
	cc.mu.Lock()
	defer cc.mu.Unlock()
	return cc.streams[id]
}

func (cc *clientConn) drop(id uint32) {
	cc.mu.Lock()
	delete(cc.streams, id)
	cc.mu.Unlock()
}

func (cc *clientConn) onSettings(f *http2.SettingsFrame) error {
	if f.IsAck() {
		return nil
	}

	var delta int32
	cc.mu.Lock()
	_ = f.ForeachSetting(func(s http2.Setting) error {
		switch s.ID {
		case http2.SettingMaxConcurrentStreams:
			cc.maxConcurrent = s.Val
		case http2.SettingInitialWindowSize:
			if s.Val > 1<<31-1 {
				return http2.ConnectionError(http2.ErrCodeFlowControl)
			}
			delta = int32(s.Val) - cc.peerInitial
			cc.peerInitial = int32(s.Val)
		case http2.SettingMaxFrameSize:
			cc.peerFrameSize = s.Val
		case http2.SettingHeaderTableSize:
			cc.henc.SetMaxDynamicTableSize(s.Val)
		}
		return nil
	})
	streams := make([]*clientStream, 0, len(cc.streams))
	for _, cs := range cc.streams {
		streams = append(streams, cs)
	}
	cc.mu.Unlock()

	if delta != 0 {
		for _, cs := range streams {
			cs.addWindow(delta)
		}
	}
	return cc.frame(cc.fr.WriteSettingsAck)
}

func (cc *clientConn) onWindowUpdate(f *http2.WindowUpdateFrame) {
	if f.StreamID != 0 {
		if cs := cc.stream(f.StreamID); cs != nil {
			cs.addWindow(int32(f.Increment))
		}
		return
	}

	cc.mu.Lock()
	cc.connSend += int32(f.Increment)
	streams := make([]*clientStream, 0, len(cc.streams))
	for _, cs := range cc.streams {
		streams = append(streams, cs)
	}
	cc.mu.Unlock()

	for _, cs := range streams {
		cs.wake()
	}
}

func (cc *clientConn) onHeaders(f *http2.MetaHeadersFrame) {
	cs := cc.stream(f.StreamID)
	if cs == nil {
		return
	}
	cc.touch()

	if cs.gotResponse {
		if f.StreamEnded() {
			cc.drop(cs.id)
			cs.body.close(io.EOF)
		}
		return
	}

	status := 0
	header := make(http.Header, len(f.Fields))
	for _, hf := range f.Fields {
		if len(hf.Name) > 0 && hf.Name[0] == ':' {
			if hf.Name == ":status" {
				status, _ = strconv.Atoi(hf.Value)
			}
			continue
		}
		header.Add(hf.Name, hf.Value)
	}
	if status >= 100 && status < 200 {
		return
	}

	cs.gotResponse = true
	resp := &http.Response{
		Status:        strconv.Itoa(status) + " " + http.StatusText(status),
		StatusCode:    status,
		Proto:         "HTTP/2.0",
		ProtoMajor:    2,
		ProtoMinor:    0,
		Header:        header,
		Body:          cs.body,
		Request:       cs.req,
		ContentLength: -1,
	}
	if text := header.Get("Content-Length"); text != "" {
		if n, err := strconv.ParseInt(text, 10, 64); err == nil {
			resp.ContentLength = n
		}
	}
	if f.StreamEnded() {
		resp.ContentLength = 0
		cc.drop(cs.id)
		cs.body.close(io.EOF)
	}
	cs.deliver(resp)
}

func (cc *clientConn) onData(f *http2.DataFrame) error {
	cc.touch()
	cs := cc.stream(f.StreamID)
	if n := len(f.Data()); n > 0 {
		cc.creditConn(uint32(n))
	}
	if cs == nil {
		return nil
	}

	if data := f.Data(); len(data) > 0 {
		cs.body.push(data)
	}
	if f.StreamEnded() {
		cc.drop(cs.id)
		cs.body.close(io.EOF)
	}
	return nil
}

// The connection half of the receive window is topped up as soon as a frame is
// accounted for; the stream half waits until the reader has actually taken the
// bytes, which is what keeps a slow consumer from turning into an unbounded
// buffer in here.
func (cc *clientConn) creditConn(n uint32) {
	cc.mu.Lock()
	cc.recvUnacked += n
	total := cc.recvUnacked
	threshold := cc.t.profile().ConnectionWindow / 2
	if total < threshold {
		cc.mu.Unlock()
		return
	}
	cc.recvUnacked = 0
	cc.mu.Unlock()

	_ = cc.frame(func() error { return cc.fr.WriteWindowUpdate(0, total) })
}

func (cc *clientConn) creditStream(id uint32, n uint32) {
	_ = cc.frame(func() error { return cc.fr.WriteWindowUpdate(id, n) })
}
