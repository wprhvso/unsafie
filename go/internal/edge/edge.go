package edge

import (
	"context"
	"errors"
	"net"
	"net/http"
	"sync"
	"sync/atomic"
	"time"

	"unsafie/internal/backoff"
	"unsafie/internal/logging"
	"unsafie/internal/service"
	"unsafie/internal/usp"
)

// Wire is one way of speaking to the edge: an HTTP/2 connection over TLS, or an
// HTTP/3 connection over QUIC. The browser we imitate keeps both in play, and
// so do we — the choice is not ours to make once and forget.
type Wire interface {
	Client() *http.Client
	Protocol() string
	Degrade(err error)
	Rebind()
	Close()
}

type Result struct {
	Edge    string
	Service string
	Fault   usp.Fault
	Reason  usp.Reason
	Latency time.Duration
	Wire    string
	Err     error
}

type Config struct {
	Name     string
	Host     string
	Port     string
	Bearer   string
	Label    string
	Slots    string
	Parallel int
	Replay   int
	Padder   usp.Padder
	State    *Store

	NewWire func(host, port string) Wire
	Report  func(Result)
}

// Edge is one of the fixed servers. It owns however many parallel sessions it
// takes to keep head of line blocking off the tunnel: an HTTP/2 leg is a single
// TCP connection, and one lost segment there stalls every stream riding on it.
type Edge struct {
	cfg   Config
	base  string
	slots []*slot

	closed atomic.Bool
	cursor atomic.Uint32

	hello   atomic.Pointer[usp.ServerHello]
	rtt     atomic.Int64
	skew    atomic.Int64
	opens   atomic.Int64
	fails   atomic.Int64
	streams atomic.Int64
	legs    atomic.Int64
}

type slot struct {
	edge  *Edge
	wire  Wire
	index int

	mu      sync.Mutex
	session *Session
	delay   *backoff.Jitter
	nextTry time.Time
	lastErr error
}

func New(cfg Config) *Edge {
	if cfg.Port == "" {
		cfg.Port = "443"
	}
	if cfg.Parallel <= 0 {
		cfg.Parallel = 3
	}
	if cfg.Replay <= 0 {
		cfg.Replay = 4 << 20
	}

	e := &Edge{cfg: cfg, base: "https://" + net.JoinHostPort(cfg.Host, cfg.Port)}
	if cfg.Port == "443" {
		e.base = "https://" + cfg.Host
	}
	for i := range cfg.Parallel {
		e.slots = append(e.slots, &slot{
			edge:  e,
			wire:  cfg.NewWire(cfg.Host, cfg.Port),
			index: i,
			delay: backoff.New(500*time.Millisecond, 30*time.Second),
		})
	}
	return e
}

func (e *Edge) Name() string { return e.cfg.Name }
func (e *Edge) Host() string { return e.cfg.Host }

func (e *Edge) RTT() time.Duration { return time.Duration(e.rtt.Load()) }

func (e *Edge) Streams() int64 { return e.streams.Load() }

func (e *Edge) Hello() (usp.ServerHello, bool) {
	h := e.hello.Load()
	if h == nil {
		return usp.ServerHello{}, false
	}
	return *h, true
}

func (e *Edge) Region() string {
	if h, ok := e.Hello(); ok {
		return h.Region
	}
	return ""
}

func (e *Edge) Country() string {
	if h, ok := e.Hello(); ok {
		return h.Country
	}
	return ""
}

func (e *Edge) Live() bool {
	for _, s := range e.slots {
		if s.live() != nil {
			return true
		}
	}
	return false
}

func (e *Edge) Protocol() string {
	if len(e.slots) == 0 {
		return ""
	}
	return e.slots[0].wire.Protocol()
}

func (e *Edge) Close() {
	if e.closed.Swap(true) {
		return
	}
	for _, s := range e.slots {
		s.shut()
		s.wire.Close()
	}
}

// Reset is what an uplink change asks for: the sockets are open and lead
// nowhere. It drops the connections and leaves the sessions alone — the legs
// redial from the offsets they already hold, and nothing riding on them
// notices that the network underneath changed.
func (e *Edge) Reset() int {
	n := 0
	for _, s := range e.slots {
		s.wire.Rebind()
		if sess := s.live(); sess != nil {
			sess.Rotate()
			n++
		}
	}
	return n
}

// Suspend stops without telling the exit, leaving it holding the sessions and
// the offsets on disk for the next run to pick up.
func (e *Edge) Suspend() {
	if e.closed.Swap(true) {
		return
	}
	for _, s := range e.slots {
		s.mu.Lock()
		sess := s.session
		s.session = nil
		s.mu.Unlock()
		if sess != nil {
			sess.Suspend()
		}
		s.wire.Close()
	}
}

func (e *Edge) Dial(ctx context.Context, network, address string) (net.Conn, error) {
	return e.dial(ctx, network, address, false)
}

// DialStrict waits for the exit to confirm the destination is reachable. It
// costs one round trip and it is what the racer wants: a hedged attempt is only
// worth anything if you can tell which copy actually connected.
func (e *Edge) DialStrict(ctx context.Context, network, address string) (net.Conn, error) {
	return e.dial(ctx, network, address, true)
}

func (e *Edge) dial(ctx context.Context, network, address string, strict bool) (net.Conn, error) {
	target, err := usp.ParseAddr(address)
	if err != nil {
		return nil, err
	}
	udp := len(network) >= 3 && network[:3] == "udp"

	started := time.Now()
	sess, err := e.session(ctx)
	if err != nil {
		e.report(err, service.Key(target.Host()), time.Since(started))
		return nil, err
	}

	var conn net.Conn
	if strict {
		conn, err = sess.mux.OpenStrict(ctx, target, udp)
	} else {
		conn, err = sess.Open(ctx, target, udp)
	}
	if err != nil {
		e.report(err, service.Key(target.Host()), time.Since(started))
		return nil, err
	}

	e.opens.Add(1)
	e.streams.Add(1)
	return &tracked{Conn: conn, edge: e}, nil
}

func (e *Edge) report(err error, key string, latency time.Duration) {
	if err != nil {
		e.fails.Add(1)
	}
	if e.cfg.Report == nil {
		return
	}
	fault, reason := Classify(err)
	e.cfg.Report(Result{
		Edge:    e.cfg.Name,
		Service: key,
		Fault:   fault,
		Reason:  reason,
		Latency: latency,
		Wire:    e.Protocol(),
		Err:     err,
	})
}

// Succeeded is how the layers above hand back the only verdict that is not
// visible from inside the tunnel: bytes actually came back from the destination.
func (e *Edge) Succeeded(key string, latency time.Duration) {
	if e.cfg.Report == nil {
		return
	}
	e.cfg.Report(Result{
		Edge:    e.cfg.Name,
		Service: key,
		Fault:   usp.FaultNone,
		Reason:  usp.ReasonNone,
		Latency: latency,
		Wire:    e.Protocol(),
	})
}

func (e *Edge) session(ctx context.Context) (*Session, error) {
	if e.closed.Load() {
		return nil, net.ErrClosed
	}

	if s := e.leastLoaded(); s != nil {
		return s, nil
	}

	start := int(e.cursor.Add(1)) % len(e.slots)
	var last error
	for i := range e.slots {
		s := e.slots[(start+i)%len(e.slots)]
		sess, err := s.ensure(ctx)
		if err == nil {
			return sess, nil
		}
		last = err
	}
	if last == nil {
		last = ErrSessionGone
	}
	return nil, last
}

func (e *Edge) leastLoaded() *Session {
	var best *Session
	bestLoad := int(^uint(0) >> 1)
	for _, s := range e.slots {
		sess := s.live()
		if sess == nil {
			continue
		}
		if n := sess.mux.Streams(); n < bestLoad {
			best, bestLoad = sess, n
		}
	}
	return best
}

// Warm opens every session up front. A tunnel that only builds its transport
// when the first packet arrives spends that packet's latency budget on a TLS
// handshake, and the user sees it as "the VPN is slow to start".
func (e *Edge) Warm(ctx context.Context) error {
	var last error
	for _, s := range e.slots {
		sess, err := s.ensure(ctx)
		if err != nil {
			last = err
			continue
		}
		if err := sess.Ready(ctx); err != nil {
			last = err
		}
	}
	return last
}

func (e *Edge) Ping(ctx context.Context) (time.Duration, error) {
	sess, err := e.session(ctx)
	if err != nil {
		return 0, err
	}
	rtt, err := sess.mux.Ping(ctx)
	if err == nil {
		e.rtt.Store(int64(rtt))
		e.skew.Store(int64(sess.mux.Skew()))
	}
	return rtt, err
}

func (s *slot) live() *Session {
	s.mu.Lock()
	defer s.mu.Unlock()
	if s.session == nil {
		return nil
	}
	select {
	case <-s.session.Done():
		s.session = nil
		return nil
	default:
	}
	return s.session
}

func (s *slot) shut() bool {
	s.mu.Lock()
	sess := s.session
	s.session = nil
	s.mu.Unlock()
	if sess == nil {
		return false
	}
	go sess.Close()
	return true
}

func (s *slot) ensure(ctx context.Context) (*Session, error) {
	if sess := s.live(); sess != nil {
		return sess, nil
	}

	s.mu.Lock()
	defer s.mu.Unlock()

	if s.session != nil {
		select {
		case <-s.session.Done():
			s.session = nil
		default:
			return s.session, nil
		}
	}
	if time.Now().Before(s.nextTry) {
		if s.lastErr != nil {
			return nil, s.lastErr
		}
		return nil, ErrSessionRefused
	}

	e := s.edge
	started := time.Now()
	sess, err := Open(ctx, SessionConfig{
		Base:        e.base,
		Bearer:      e.cfg.Bearer,
		Label:       e.cfg.Label,
		Slots:       e.cfg.Slots,
		Edge:        e.cfg.Name,
		Slot:        s.index,
		State:       e.cfg.State,
		Client:      s.wire.Client(),
		ReplayBytes: e.cfg.Replay,
		Padder:      e.cfg.Padder,
		Wire:        s.wire.Protocol,
		Remote:      &edgeAddr{host: e.cfg.Host, port: e.cfg.Port},
		OnFault:     e.onFault,
		OnRTT: func(rtt, skew time.Duration) {
			e.rtt.Store(int64(rtt))
			e.skew.Store(int64(skew))
		},
		OnHello: func(h usp.ServerHello, spent time.Duration) {
			e.hello.Store(&h)
			e.report(nil, "", spent)
			how := "up"
			if h.Resumed {
				how = "resumed"
			}
			logging.Infof("Edge %s: session %s over %s from %s/%s in %s",
				e.cfg.Name, how, s.wire.Protocol(), h.Region, h.Country, spent.Round(time.Millisecond))
		},
		OnLeg: func(kind string, err error) {
			e.legs.Add(1)
			if err == nil {
				return
			}
			logging.Infof("Edge %s: %s leg ended: %v", e.cfg.Name, kind, err)
			s.wire.Degrade(err)
			e.report(err, "", 0)
		},
	})
	if err != nil {
		s.lastErr = err
		s.nextTry = time.Now().Add(s.delay.Next())
		e.report(err, "", time.Since(started))
		return nil, err
	}

	s.delay.Reset()
	s.lastErr = nil
	s.session = sess
	return sess, nil
}

func (e *Edge) onFault(reason usp.Reason, target usp.Addr) {
	if e.cfg.Report == nil {
		return
	}
	e.cfg.Report(Result{
		Edge:    e.cfg.Name,
		Service: service.Key(target.Host()),
		Fault:   reason.Blames(),
		Reason:  reason,
		Wire:    e.Protocol(),
		Err:     reason,
	})
}

type tracked struct {
	net.Conn
	edge *Edge
	once sync.Once
}

func (c *tracked) Close() error {
	c.once.Do(func() { c.edge.streams.Add(-1) })
	return c.Conn.Close()
}

func (c *tracked) CloseWrite() error {
	if cw, ok := c.Conn.(interface{ CloseWrite() error }); ok {
		return cw.CloseWrite()
	}
	return errors.ErrUnsupported
}

func (c *tracked) SetReadLinger(d time.Duration) {
	if l, ok := c.Conn.(interface{ SetReadLinger(time.Duration) }); ok {
		l.SetReadLinger(d)
	}
}

type edgeAddr struct{ host, port string }

func (a *edgeAddr) Network() string { return "usp" }
func (a *edgeAddr) String() string  { return net.JoinHostPort(a.host, a.port) }
