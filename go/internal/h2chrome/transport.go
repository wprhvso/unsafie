package h2chrome

import (
	"context"
	"errors"
	"net"
	"net/http"
	"sync"
	"time"

	"golang.org/x/net/http2"
)

// Transport is an http.RoundTripper that speaks HTTP/2 the way one pinned build
// of Chrome speaks it. One transport keeps one connection, which is also what a
// browser does per origin.
type Transport struct {
	DialTLS     func(ctx context.Context, network, addr string) (net.Conn, error)
	Profile     Profile
	Addr        string
	IdleTimeout time.Duration

	mu sync.Mutex
	cc *clientConn
}

var errNoDialer = errors.New("h2chrome: no TLS dialer")

func (t *Transport) profile() Profile {
	if len(t.Profile.Settings) == 0 {
		return Chrome131
	}
	return t.Profile
}

func (t *Transport) Fingerprint() string { return t.profile().Fingerprint() }

func (t *Transport) CloseIdleConnections() {
	t.mu.Lock()
	cc := t.cc
	t.cc = nil
	t.mu.Unlock()

	if cc != nil {
		cc.closeWithError(errClosed)
	}
}

func (t *Transport) forget(cc *clientConn) {
	t.mu.Lock()
	if t.cc == cc {
		t.cc = nil
	}
	t.mu.Unlock()
}

func (t *Transport) address(req *http.Request) string {
	if t.Addr != "" {
		return t.Addr
	}
	host := req.URL.Host
	if _, _, err := net.SplitHostPort(host); err != nil {
		return net.JoinHostPort(host, "443")
	}
	return host
}

func (t *Transport) connection(ctx context.Context, req *http.Request) (*clientConn, error) {
	t.mu.Lock()
	defer t.mu.Unlock()

	if cc := t.cc; cc != nil {
		if cc.usable() && (t.IdleTimeout <= 0 || cc.idleFor() < t.IdleTimeout) {
			return cc, nil
		}
		t.cc = nil
		go cc.closeWithError(errClosed)
	}

	if t.DialTLS == nil {
		return nil, errNoDialer
	}
	conn, err := t.DialTLS(ctx, "tcp", t.address(req))
	if err != nil {
		return nil, err
	}
	cc, err := newClientConn(t, conn)
	if err != nil {
		_ = conn.Close()
		return nil, err
	}
	t.cc = cc
	return cc, nil
}

func (t *Transport) RoundTrip(req *http.Request) (*http.Response, error) {
	if req.URL == nil {
		return nil, errors.New("h2chrome: no URL")
	}

	retriable := req.Body == nil || req.GetBody != nil
	for attempt := range 2 {
		cc, err := t.connection(req.Context(), req)
		if err != nil {
			return nil, err
		}
		resp, err := cc.roundTrip(req)
		if err == nil {
			return resp, nil
		}
		if attempt == 0 && retriable && errors.Is(err, ErrRetry) {
			if req.GetBody != nil {
				body, berr := req.GetBody()
				if berr != nil {
					return nil, err
				}
				req.Body = body
			}
			continue
		}
		return nil, err
	}
	return nil, ErrRetry
}

func (cc *clientConn) failure() error {
	cc.mu.Lock()
	defer cc.mu.Unlock()
	if cc.err != nil {
		return cc.err
	}
	return errClosed
}

func (cc *clientConn) roundTrip(req *http.Request) (*http.Response, error) {
	cs, err := cc.writeRequest(req)
	if err != nil {
		return nil, err
	}
	if req.Body != nil {
		go cs.writeBody(req.Body)
	}

	ctx := req.Context()
	select {
	case resp := <-cs.resp:
		return resp, nil
	case <-cs.done:
		return nil, cs.failure()
	case <-cc.closed:
		return nil, cc.failure()
	case <-ctx.Done():
		cs.cancel()
		return nil, ctx.Err()
	}
}

// writeRequest holds the write lock across allocation and the HEADERS frame:
// stream identifiers have to reach the peer in increasing order, and any gap
// between picking one and sending it is a race that ends in a protocol error.
func (cc *clientConn) writeRequest(req *http.Request) (*clientStream, error) {
	profile := cc.t.profile()

	cc.wmu.Lock()
	defer cc.wmu.Unlock()

	cc.mu.Lock()
	switch {
	case cc.err != nil:
		err := cc.err
		cc.mu.Unlock()
		return nil, err
	case cc.goingAway:
		cc.mu.Unlock()
		return nil, ErrRetry
	case uint32(len(cc.streams)) >= cc.maxConcurrent:
		cc.mu.Unlock()
		return nil, errors.New("h2chrome: too many concurrent streams")
	}
	id := cc.nextID
	cc.nextID += 2
	cs := newClientStream(cc, id, req)
	cc.streams[id] = cs
	cc.mu.Unlock()

	cc.hbuf.Reset()
	if err := profile.encode(cc.henc, req, req.ContentLength); err != nil {
		cc.drop(id)
		return nil, err
	}

	block := cc.hbuf.Bytes()
	frame := int(cc.peerFrameSize)
	first := block
	if len(first) > frame {
		first = first[:frame]
	}
	rest := block[len(first):]

	param := http2.HeadersFrameParam{
		StreamID:      id,
		BlockFragment: first,
		EndStream:     req.Body == nil,
		EndHeaders:    len(rest) == 0,
	}
	if p := profile.Priority; p != nil {
		param.Priority = http2.PriorityParam{
			StreamDep: p.StreamDep,
			Exclusive: p.Exclusive,
			Weight:    p.Weight,
		}
	}

	if err := cc.fr.WriteHeaders(param); err != nil {
		cc.drop(id)
		return nil, err
	}
	for len(rest) > 0 {
		chunk := rest
		if len(chunk) > frame {
			chunk = chunk[:frame]
		}
		rest = rest[len(chunk):]
		if err := cc.fr.WriteContinuation(id, len(rest) == 0, chunk); err != nil {
			cc.drop(id)
			return nil, err
		}
	}
	if err := cc.bw.Flush(); err != nil {
		cc.drop(id)
		return nil, ErrRetry
	}

	cc.touch()
	return cs, nil
}
