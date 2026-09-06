package edge

import (
	"bytes"
	"context"
	"crypto/rand"
	"encoding/base64"
	"errors"
	"fmt"
	"io"
	rand2 "math/rand/v2"
	"net"
	"net/http"
	"strconv"
	"sync"
	"sync/atomic"
	"time"

	"unsafie/internal/backoff"
	"unsafie/internal/logging"
	"unsafie/internal/usp"
)

const (
	PathUp    = "/proxy/u/"
	PathDown  = "/proxy/d/"
	PathClose = "/proxy/c/"

	HeaderUp   = "X-Usp-Up"
	HeaderDown = "X-Usp-Down"
	HeaderWire = "X-Usp-Wire"

	SessionIDLen = 22
	DefaultSlots = "a"

	legTTL       = 55 * time.Second
	legTTLSpread = 0.25
	keepalive    = 15 * time.Second
	reviveWindow = 90 * time.Second
	closeTimeout = 3 * time.Second
	helloTimeout = 12 * time.Second
	maxReply     = 4 << 10
)

var (
	// ErrSessionRefused is nginx or the exit saying no before any frame was
	// ever exchanged, which is a different thing from a session that worked
	// and then stopped.
	ErrSessionRefused = errors.New("edge: session refused")
	ErrUnrecoverable  = errors.New("edge: session cannot be resumed")
)

type StatusError struct {
	Status int
	Body   string
}

func (e *StatusError) Error() string {
	if e.Body == "" {
		return "edge: " + strconv.Itoa(e.Status)
	}
	return "edge: " + strconv.Itoa(e.Status) + ": " + e.Body
}

type SessionConfig struct {
	Base          string
	Bearer        string
	Label         string
	Slots         string
	Client        *http.Client
	StreamWindow  int64
	SessionWindow int64
	ReplayBytes   int
	MaxStreams    int
	Padder        usp.Padder
	Wire          func() string
	OnFault       func(usp.Reason, usp.Addr)
	OnRTT         func(time.Duration, time.Duration)
	OnLeg         func(kind string, err error)
	OnHello       func(usp.ServerHello, time.Duration)
	Remote        net.Addr
}

type Session struct {
	cfg SessionConfig
	mux *Mux

	id      string
	started time.Time
	hello   atomic.Pointer[usp.ServerHello]
	ready   chan struct{}
	once    sync.Once

	closed atomic.Bool
	cancel context.CancelFunc
	wg     sync.WaitGroup

	legs   atomic.Int64
	revive atomic.Int64
}

// mintSession names the session on the client side, which is what makes the
// whole thing zero round trip: both legs can leave at once because neither has
// to wait to be told where to go.
//
// The first character picks the exit process — nginx maps it to a backend — and
// the remaining 126 bits make the name unguessable to anyone who got past the
// bearer token at the edge.
func mintSession(slots string) string {
	if slots == "" {
		slots = DefaultSlots
	}
	var raw [16]byte
	_, _ = rand.Read(raw[:])
	id := base64.RawURLEncoding.EncodeToString(raw[:])
	return string(slots[rand2.IntN(len(slots))]) + id[1:]
}

// Open costs nothing on the wire. Both legs and the hello leave together; the
// exit creates the session when it first sees the name and answers with a
// HELLO_ACK frame at offset zero of the downlink.
func Open(ctx context.Context, cfg SessionConfig) (*Session, error) {
	if cfg.Client == nil {
		return nil, errors.New("edge: no HTTP client")
	}
	if cfg.StreamWindow == 0 {
		cfg.StreamWindow = usp.DefaultStreamWindow
	}
	if cfg.SessionWindow == 0 {
		cfg.SessionWindow = usp.DefaultSessionWindow
	}
	if cfg.ReplayBytes == 0 {
		cfg.ReplayBytes = 4 << 20
	}
	if cfg.MaxStreams == 0 {
		cfg.MaxStreams = 4096
	}

	var nonce [16]byte
	_, _ = rand.Read(nonce[:])

	hello := usp.ClientHello{
		Version:       usp.Version,
		Nonce:         nonce,
		StreamWindow:  uint32(cfg.StreamWindow),
		SessionWindow: uint32(cfg.SessionWindow),
		Features: usp.FeatureUDP | usp.FeatureResume | usp.FeatureHappyEyeballs |
			usp.FeatureExitDNS | usp.FeatureStats | usp.FeaturePadding,
		SentAtMicros: uint64(time.Now().UnixMicro()),
		Label:        cfg.Label,
	}
	if cfg.Wire != nil {
		hello.Wire = cfg.Wire()
	}

	runCtx, cancel := context.WithCancel(context.WithoutCancel(ctx))
	s := &Session{
		cfg:     cfg,
		id:      mintSession(cfg.Slots),
		started: time.Now(),
		ready:   make(chan struct{}),
		cancel:  cancel,
	}
	s.mux = newMux(muxConfig{
		StreamWindow:  cfg.StreamWindow,
		SessionWindow: cfg.SessionWindow,
		ReplayBytes:   cfg.ReplayBytes,
		MaxStreams:    cfg.MaxStreams,
		Padder:        cfg.Padder,
		OnFault:       cfg.OnFault,
		OnRTT:         cfg.OnRTT,
		OnHello:       s.onHello,
		Local:         &net.TCPAddr{IP: net.IPv4zero},
		Remote:        cfg.Remote,
	})
	s.mux.seed(&usp.Frame{Type: usp.TypeHello, Flags: usp.FlagUrgent, Payload: hello.Encode()})

	s.wg.Add(3)
	go func() { defer s.wg.Done(); s.pump(runCtx, "down", s.downLeg) }()
	go func() { defer s.wg.Done(); s.pump(runCtx, "up", s.upLeg) }()
	go func() { defer s.wg.Done(); s.keepalive(runCtx) }()

	return s, nil
}

func (s *Session) onHello(h usp.ServerHello) {
	s.hello.Store(&h)
	s.once.Do(func() { close(s.ready) })
	if s.cfg.OnHello != nil {
		s.cfg.OnHello(h, time.Since(s.started))
	}
}

func (s *Session) ID() string { return s.id }

func (s *Session) Hello() usp.ServerHello {
	if h := s.hello.Load(); h != nil {
		return *h
	}
	return usp.ServerHello{}
}

// Ready waits for the exit to introduce itself. Nothing on the data path needs
// it — streams open optimistically — but the prober and the logs do.
func (s *Session) Ready(ctx context.Context) error {
	select {
	case <-s.ready:
		return nil
	case <-s.mux.Done():
		return s.mux.failure()
	case <-ctx.Done():
		return ctx.Err()
	}
}

func (s *Session) Mux() *Mux { return s.mux }

func (s *Session) Done() <-chan struct{} { return s.mux.Done() }

func (s *Session) Legs() int64 { return s.legs.Load() }

func (s *Session) Open(ctx context.Context, target usp.Addr, udp bool) (net.Conn, error) {
	return s.mux.Open(ctx, target, udp)
}

func (s *Session) Close() {
	if s.closed.Swap(true) {
		return
	}
	s.cancel()
	s.mux.Close(net.ErrClosed)

	ctx, cancel := context.WithTimeout(context.Background(), closeTimeout)
	defer cancel()
	_, _ = post(ctx, s.cfg, s.cfg.Base+PathClose+s.id, nil)
	s.wg.Wait()
}

// pump keeps one half of the session attached. A leg that dies is not a session
// that died: the frame stream has absolute offsets, so the next leg picks up
// mid sentence. Only running out of the resume window, or out of patience, ends
// the session.
func (s *Session) pump(ctx context.Context, kind string, leg func(context.Context) error) {
	delay := backoff.New(120*time.Millisecond, 5*time.Second)

	for ctx.Err() == nil && !s.closed.Load() {
		start := time.Now()
		err := leg(ctx)
		s.legs.Add(1)

		if s.cfg.OnLeg != nil {
			s.cfg.OnLeg(kind, err)
		}
		if ctx.Err() != nil || s.closed.Load() {
			return
		}

		switch {
		case err == nil, errors.Is(err, io.EOF), errors.Is(err, context.DeadlineExceeded):
			if time.Since(start) > 2*time.Second {
				delay.Reset()
			}
		case errors.Is(err, ErrUnrecoverable):
			logging.Infof("Session %s: %s leg cannot resume: %v", s.short(), kind, err)
			s.mux.Close(err)
			return
		default:
			if s.giveUp(err) {
				s.mux.Close(err)
				return
			}
		}

		select {
		case <-ctx.Done():
			return
		case <-time.After(delay.Next()):
		}
	}
}

// giveUp is the "how long may a session be broken before it is dead" rule. One
// failure is weather; a session that has not managed to hold a leg for a minute
// and a half is a session the picker should be told about so it can move on.
func (s *Session) giveUp(err error) bool {
	var status *StatusError
	if errors.As(err, &status) {
		switch status.Status {
		case http.StatusNotFound, http.StatusGone, http.StatusConflict,
			http.StatusMisdirectedRequest, http.StatusUnauthorized, http.StatusForbidden:
			return true
		}
	}
	now := time.Now().UnixNano()
	first := s.revive.Load()
	if first == 0 {
		s.revive.CompareAndSwap(0, now)
		return false
	}
	return time.Duration(now-first) > reviveWindow
}

func (s *Session) short() string {
	if len(s.id) > 8 {
		return s.id[:8]
	}
	return s.id
}

func (s *Session) downLeg(ctx context.Context) error {
	legCtx, cancel := context.WithCancel(ctx)
	defer cancel()

	req, err := http.NewRequestWithContext(legCtx, http.MethodGet, s.cfg.Base+PathDown+s.id, nil)
	if err != nil {
		return err
	}
	s.decorate(req)
	req.Header.Set(HeaderDown, strconv.FormatInt(s.mux.DownlinkAt(), 10))

	resp, err := s.cfg.Client.Do(req)
	if err != nil {
		return err
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		return statusError(resp)
	}
	s.revive.Store(0)

	stop := time.AfterFunc(backoff.Spread(legTTL, legTTLSpread), cancel)
	defer stop.Stop()

	err = s.mux.attachDown(resp.Body)
	if errors.Is(err, errGoaway) {
		return err
	}
	if legCtx.Err() != nil && ctx.Err() == nil {
		return nil
	}
	return err
}

func (s *Session) upLeg(ctx context.Context) error {
	legCtx, cancel := context.WithCancel(ctx)
	defer cancel()

	from := s.mux.UplinkAt()
	pr, pw := io.Pipe()

	req, err := http.NewRequestWithContext(legCtx, http.MethodPost, s.cfg.Base+PathUp+s.id, pr)
	if err != nil {
		return err
	}
	s.decorate(req)
	req.Header.Set(HeaderUp, strconv.FormatInt(from, 10))
	req.Header.Set("Content-Type", "application/octet-stream")

	// The request has to be in flight before the first byte of backlog is
	// written: an io.Pipe blocks until somebody reads it, and the only reader
	// is the transport this call sets going.
	answered := make(chan struct{})
	var resp *http.Response
	var reqErr error
	go func() {
		defer close(answered)
		resp, reqErr = s.cfg.Client.Do(req)
	}()

	if err := s.mux.attachUp(pw, from); err != nil {
		_ = pw.CloseWithError(err)
		<-answered
		if resp != nil {
			_ = resp.Body.Close()
		}
		if errors.Is(err, errReplayGone) {
			return fmt.Errorf("%w: %w", ErrUnrecoverable, err)
		}
		return err
	}
	defer s.mux.detachUp()

	stop := time.AfterFunc(backoff.Spread(legTTL, legTTLSpread), func() {
		_ = pw.Close()
	})
	defer stop.Stop()

	<-answered
	if reqErr != nil {
		_ = pw.CloseWithError(reqErr)
		return reqErr
	}
	defer resp.Body.Close()
	_, _ = io.Copy(io.Discard, io.LimitReader(resp.Body, maxReply))

	if resp.StatusCode/100 != 2 {
		return statusError(resp)
	}
	s.revive.Store(0)
	return nil
}

func (s *Session) keepalive(ctx context.Context) {
	interval := keepalive
	waitCtx, cancel := context.WithTimeout(ctx, helloTimeout)
	if err := s.Ready(waitCtx); err == nil {
		if ms := s.Hello().KeepaliveMS; ms > 0 {
			interval = time.Duration(ms) * time.Millisecond
		}
	}
	cancel()

	t := time.NewTicker(interval)
	defer t.Stop()

	misses := 0
	for {
		select {
		case <-ctx.Done():
			return
		case <-s.mux.Done():
			return
		case <-t.C:
		}

		pingCtx, cancel := context.WithTimeout(ctx, interval)
		_, err := s.mux.Ping(pingCtx)
		cancel()
		if err == nil {
			misses = 0
			continue
		}
		misses++
		if misses >= 3 {
			s.mux.Close(fmt.Errorf("edge: %d keepalives went unanswered", misses))
			return
		}
	}
}

func (s *Session) decorate(req *http.Request) {
	if s.cfg.Bearer != "" {
		req.Header.Set("Authorization", "Bearer "+s.cfg.Bearer)
	}
	if s.cfg.Wire != nil {
		req.Header.Set(HeaderWire, s.cfg.Wire())
	}
	req.Header.Set("Cache-Control", "no-store")
}

func post(ctx context.Context, cfg SessionConfig, url string, body []byte) ([]byte, error) {
	var reader io.Reader
	if len(body) > 0 {
		reader = bytes.NewReader(body)
	}
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, url, reader)
	if err != nil {
		return nil, err
	}
	if cfg.Bearer != "" {
		req.Header.Set("Authorization", "Bearer "+cfg.Bearer)
	}
	req.Header.Set("Content-Type", "application/octet-stream")
	req.Header.Set("Cache-Control", "no-store")
	if len(body) > 0 {
		req.ContentLength = int64(len(body))
	}

	resp, err := cfg.Client.Do(req)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()

	if resp.StatusCode/100 != 2 {
		return nil, statusError(resp)
	}
	return io.ReadAll(io.LimitReader(resp.Body, maxReply))
}

func statusError(resp *http.Response) error {
	snippet, _ := io.ReadAll(io.LimitReader(resp.Body, 256))
	return &StatusError{Status: resp.StatusCode, Body: string(snippet)}
}
