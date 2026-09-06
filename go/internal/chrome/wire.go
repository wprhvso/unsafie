package chrome

import (
	"context"
	"crypto/tls"
	"crypto/x509"
	"errors"
	"fmt"
	"net"
	"net/http"
	"sync"
	"sync/atomic"
	"time"

	utls "github.com/refraction-networking/utls"
	"golang.org/x/net/http2"

	"unsafie/internal/backoff"
	"unsafie/internal/logging"
	"unsafie/internal/netx"
)

const (
	// Chrome gives QUIC a head start and only falls back to TCP if the QUIC
	// handshake has not completed by then. Racing them from zero would make the
	// fast path lose on any connection where TCP happens to be a millisecond
	// ahead, which is most of them on a good network.
	quicHeadStart = 250 * time.Millisecond

	probePath      = "/proxy/p"
	probeTimeout   = 6 * time.Second
	h3BreakBase    = 5 * time.Minute
	h3BreakMax     = 2 * time.Hour
	negotiateEvery = 10 * time.Minute
)

type Options struct {
	Profile    Profile
	Host       string
	Port       string
	Dial       netx.DialFunc
	ListenUDP  func(ctx context.Context) (net.PacketConn, error)
	ResolveUDP func(ctx context.Context, host, port string) (*net.UDPAddr, error)
	Insecure   bool
	RootCAs    *x509.CertPool
	EnableH3   bool
	AllowRetry bool
}

// Wire is one browser-shaped way of reaching one host. It owns both protocols a
// current Chrome will use and the rules for moving between them, because those
// rules are themselves part of the fingerprint: a client that speaks only
// HTTP/3, or only HTTP/2, or that switches on a schedule nobody else uses, is
// distinguishable no matter how perfect its ClientHello is.
type Wire struct {
	opts    Options
	profile Profile
	base    string

	client *http.Client

	h2 http.RoundTripper
	h3 http.RoundTripper

	mu           sync.Mutex
	h3Advertised time.Time
	h3Expires    time.Time
	h3BrokenTill time.Time
	h3Backoff    *backoff.Jitter
	negotiating  bool
	negotiatedAt time.Time

	preferred atomic.Value
	closed    atomic.Bool
}

func NewWire(o Options) *Wire {
	if o.Port == "" {
		o.Port = "443"
	}
	if o.Profile.Name == "" {
		o.Profile = Chrome131
	}

	w := &Wire{
		opts:      o,
		profile:   o.Profile,
		h3Backoff: backoff.New(h3BreakBase, h3BreakMax),
	}
	w.base = "https://" + o.Host
	if o.Port != "443" {
		w.base = "https://" + net.JoinHostPort(o.Host, o.Port)
	}
	w.preferred.Store("h2")

	w.h2 = w.newH2()
	if o.EnableH3 {
		w.h3 = w.newH3()
	}

	w.client = &http.Client{
		Transport: &decorator{next: w, profile: w.profile, origin: w.base},
		CheckRedirect: func(*http.Request, []*http.Request) error {
			return http.ErrUseLastResponse
		},
	}
	return w
}

func (w *Wire) Client() *http.Client { return w.client }

func (w *Wire) Protocol() string {
	p, _ := w.preferred.Load().(string)
	return p
}

func (w *Wire) Close() {
	if w.closed.Swap(true) {
		return
	}
	closeIdle(w.h2)
	closeIdle(w.h3)
}

func closeIdle(rt http.RoundTripper) {
	if c, ok := rt.(interface{ CloseIdleConnections() }); ok {
		c.CloseIdleConnections()
	}
}

// Degrade is the only thing the layers above have to say about protocols: this
// did not work. What that means for HTTP/3 versus HTTP/2 is decided here.
func (w *Wire) Degrade(err error) {
	if err == nil {
		return
	}
	if w.Protocol() == "h3" {
		w.breakH3(err)
		return
	}
	closeIdle(w.h2)
}

func (w *Wire) breakH3(err error) {
	w.mu.Lock()
	cool := w.h3Backoff.Next()
	w.h3BrokenTill = time.Now().Add(cool)
	w.mu.Unlock()

	w.preferred.Store("h2")
	closeIdle(w.h3)
	logging.Infof("Wire %s: HTTP/3 marked broken for %s: %v", w.opts.Host, cool.Round(time.Second), err)
}

func (w *Wire) h3Usable(now time.Time) bool {
	if w.h3 == nil {
		return false
	}
	w.mu.Lock()
	defer w.mu.Unlock()
	if now.Before(w.h3BrokenTill) {
		return false
	}
	return !w.h3Expires.IsZero() && now.Before(w.h3Expires)
}

func (w *Wire) RoundTrip(req *http.Request) (*http.Response, error) {
	now := time.Now()
	w.maybeNegotiate(req.Context(), now)

	rt, proto := w.h2, "h2"
	if w.h3Usable(now) {
		rt, proto = w.h3, "h3"
	}

	resp, err := rt.RoundTrip(req)
	if err != nil {
		if proto == "h3" {
			w.breakH3(err)
			if w.opts.AllowRetry && req.Body == nil {
				return w.h2.RoundTrip(req)
			}
		}
		return nil, err
	}

	w.learn(resp.Header.Get("Alt-Svc"))
	w.preferred.Store(proto)
	return resp, nil
}

func (w *Wire) learn(header string) {
	alt, ok := parseAltSvc(header)
	if !ok || !alt.h3 {
		return
	}
	w.mu.Lock()
	first := w.h3Advertised.IsZero()
	if first {
		w.h3Advertised = time.Now()
	}
	w.h3Expires = time.Now().Add(alt.ttl)
	w.mu.Unlock()

	if first && w.h3 != nil {
		logging.Infof("Wire %s: the edge advertises HTTP/3; racing it on the next connection.", w.opts.Host)
	}
}

// maybeNegotiate reproduces the moment a browser decides to try QUIC. It sends
// one cheap request over each protocol, gives QUIC the head start Chrome gives
// it, and keeps whichever answered first. Nothing that carries a session ever
// takes part in the race: a streaming upload cannot be replayed on the loser.
func (w *Wire) maybeNegotiate(ctx context.Context, now time.Time) {
	if w.h3 == nil || w.closed.Load() {
		return
	}

	w.mu.Lock()
	if w.negotiating || now.Before(w.h3BrokenTill) || now.Sub(w.negotiatedAt) < negotiateEvery {
		w.mu.Unlock()
		return
	}
	if w.h3Expires.IsZero() && !w.h3Advertised.IsZero() {
		w.mu.Unlock()
		return
	}
	w.negotiating = true
	w.mu.Unlock()

	go w.negotiate(context.WithoutCancel(ctx))
}

func (w *Wire) negotiate(parent context.Context) {
	defer func() {
		w.mu.Lock()
		w.negotiating = false
		w.negotiatedAt = time.Now()
		w.mu.Unlock()
	}()

	ctx, cancel := context.WithTimeout(parent, probeTimeout)
	defer cancel()

	type outcome struct {
		proto string
		resp  *http.Response
		err   error
	}
	results := make(chan outcome, 2)

	probe := func(proto string, rt http.RoundTripper, delay time.Duration) {
		if delay > 0 {
			select {
			case <-time.After(delay):
			case <-ctx.Done():
				results <- outcome{proto: proto, err: ctx.Err()}
				return
			}
		}
		req, err := http.NewRequestWithContext(ctx, http.MethodGet, w.base+probePath, nil)
		if err != nil {
			results <- outcome{proto: proto, err: err}
			return
		}
		(&decorator{next: nopRT{}, profile: w.profile, origin: w.base}).RoundTrip(req) //nolint:errcheck // fills headers only
		resp, err := rt.RoundTrip(req)
		results <- outcome{proto: proto, resp: resp, err: err}
	}

	go probe("h3", w.h3, 0)
	go probe("h2", w.h2, quicHeadStart)

	for range 2 {
		select {
		case r := <-results:
			if r.resp != nil {
				w.learn(r.resp.Header.Get("Alt-Svc"))
				_ = r.resp.Body.Close()
			}
			if r.err != nil {
				if r.proto == "h3" {
					w.breakH3(r.err)
				}
				continue
			}
			if r.proto == "h3" {
				w.mu.Lock()
				w.h3Backoff.Reset()
				if w.h3Expires.IsZero() {
					w.h3Expires = time.Now().Add(time.Hour)
				}
				w.mu.Unlock()
				w.preferred.Store("h3")
				logging.Infof("Wire %s: HTTP/3 won the race; using QUIC.", w.opts.Host)
			}
			return
		case <-ctx.Done():
			return
		}
	}
}

type nopRT struct{}

func (nopRT) RoundTrip(*http.Request) (*http.Response, error) { return nil, errNoop }

var errNoop = errors.New("chrome: header decoration only")

func (w *Wire) newH2() http.RoundTripper {
	return &http2.Transport{
		DialTLSContext:             w.dialTLS,
		MaxHeaderListSize:          w.profile.MaxHeaderListSize,
		MaxReadFrameSize:           w.profile.MaxFrameSize,
		MaxDecoderHeaderTableSize:  w.profile.HeaderTableSize,
		MaxEncoderHeaderTableSize:  w.profile.HeaderTableSize,
		StrictMaxConcurrentStreams: true,
		ReadIdleTimeout:            15 * time.Second,
		PingTimeout:                8 * time.Second,
		WriteByteTimeout:           30 * time.Second,
		DisableCompression:         true,
	}
}

func (w *Wire) dialTLS(ctx context.Context, network, addr string, _ *tls.Config) (net.Conn, error) {
	dial := w.opts.Dial
	if dial == nil {
		var d net.Dialer
		dial = d.DialContext
	}

	raw, err := dial(ctx, network, addr)
	if err != nil {
		return nil, err
	}

	conn := utls.UClient(raw, &utls.Config{
		ServerName:         w.opts.Host,
		NextProtos:         w.profile.ALPN,
		InsecureSkipVerify: w.opts.Insecure,
		RootCAs:            w.opts.RootCAs,
		ClientSessionCache: utls.NewLRUClientSessionCache(32),
	}, w.profile.Hello)

	if err := conn.HandshakeContext(ctx); err != nil {
		_ = raw.Close()
		return nil, err
	}
	if proto := conn.ConnectionState().NegotiatedProtocol; proto != "h2" {
		_ = conn.Close()
		return nil, fmt.Errorf("chrome: the edge negotiated %q, not h2", proto)
	}
	return conn, nil
}
