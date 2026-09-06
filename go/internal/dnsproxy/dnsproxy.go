package dnsproxy

import (
	"context"
	"errors"
	"net/netip"
	"strconv"
	"sync"
	"sync/atomic"
	"time"

	"github.com/miekg/dns"

	"unsafie/internal/dnsx"
	"unsafie/internal/logging"
	"unsafie/internal/rules"
)

const (
	Timeout = 5 * time.Second

	sweepInterval = time.Minute

	startupGrace = 5 * time.Second
)

type Resolver interface {
	Resolve(ctx context.Context, m *dns.Msg, qtype uint16) (*dns.Msg, error)
}

type ResolverFunc func(ctx context.Context, m *dns.Msg, qtype uint16) (*dns.Msg, error)

var ErrNoResolver = errors.New("dnsproxy: no resolver")

func (f ResolverFunc) Resolve(ctx context.Context, m *dns.Msg, qtype uint16) (*dns.Msg, error) {
	if f == nil {
		return nil, ErrNoResolver
	}
	return f(ctx, m, qtype)
}

type Rules interface{ LookupDomain(host string) bool }

type Peer interface{ MatchesHost(host string) bool }

type Learner interface {
	Learn(addr netip.Addr)
	Sweep(now time.Time)
}

type Options struct {
	Addr string

	Rules   Rules
	Peer    Peer
	Learner Learner

	Direct Resolver
	Tunnel Resolver

	Timeout time.Duration
}

type Server struct {
	opts  Options
	cache *Cache

	base atomic.Pointer[context.Context]

	mu      sync.Mutex
	running []*dns.Server
}

func New(o Options) *Server {
	if o.Timeout <= 0 {
		o.Timeout = Timeout
	}
	return &Server{opts: o, cache: newCache()}
}

func (s *Server) Cache() *Cache { return s.cache }

func (s *Server) context() context.Context {
	if ctx := s.base.Load(); ctx != nil {
		return *ctx
	}
	return context.Background()
}

func (s *Server) Handler() dns.Handler {
	return dns.HandlerFunc(func(w dns.ResponseWriter, r *dns.Msg) {
		resp := s.answer(s.context(), r)
		if resp == nil {
			dns.HandleFailed(w, r)
			return
		}
		_ = w.WriteMsg(resp)
	})
}

func (s *Server) answer(ctx context.Context, r *dns.Msg) *dns.Msg {
	if len(r.Question) == 0 {
		return nil
	}

	q := r.Question[0]
	host, ok := rules.Normalize(q.Name)
	if !ok {
		return nil
	}

	if q.Qtype == dns.TypeAAAA {
		return emptyReply(r, true)
	}

	key := host + ":" + strconv.Itoa(int(q.Qtype))
	if resp := s.cache.Get(key, r); resp != nil {
		return resp
	}

	var last *dns.Msg
	tried := false

	if s.goesDirect(host) {
		tried = true
		last = s.ask(ctx, s.opts.Direct, r, q.Qtype)
		if dnsx.Answered(last, q.Qtype) {
			s.learn(last.Answer)
			s.cache.Put(key, last)
			return last
		}
	}

	switch {
	case q.Qtype == dns.TypeA:
		if resp := s.ask(ctx, s.opts.Tunnel, r, q.Qtype); dnsx.Answered(resp, q.Qtype) {
			s.cache.Put(key, resp)
			return resp
		}
	case !tried:
		return emptyReply(r, false)
	}

	if resp := s.cache.Stale(key, r); resp != nil {
		return resp
	}
	return last
}

func (s *Server) goesDirect(host string) bool {
	if s.opts.Peer != nil && s.opts.Peer.MatchesHost(host) {
		return true
	}
	return s.opts.Rules != nil && s.opts.Rules.LookupDomain(host)
}

func (s *Server) ask(ctx context.Context, res Resolver, r *dns.Msg, qtype uint16) *dns.Msg {
	if res == nil {
		return nil
	}
	ctx, cancel := context.WithTimeout(ctx, s.opts.Timeout)
	defer cancel()

	resp, err := res.Resolve(ctx, r, qtype)
	if err != nil {
		return nil
	}
	return resp
}

func (s *Server) learn(answer []dns.RR) {
	if s.opts.Learner == nil {
		return
	}
	for _, ans := range answer {
		a, ok := ans.(*dns.A)
		if !ok {
			continue
		}
		if addr, ok := netip.AddrFromSlice(a.A.To4()); ok {
			s.opts.Learner.Learn(addr)
		}
	}
}

func emptyReply(r *dns.Msg, authoritative bool) *dns.Msg {
	resp := new(dns.Msg)
	resp.SetReply(r)
	resp.Authoritative = authoritative
	resp.RecursionAvailable = !authoritative
	return resp
}

func (s *Server) Serve(ctx context.Context) error {
	s.base.Store(&ctx)

	var wg sync.WaitGroup
	defer wg.Wait()

	handler := s.Handler()
	servers := []*dns.Server{
		{Addr: s.opts.Addr, Net: "udp", Handler: handler},
		{Addr: s.opts.Addr, Net: "tcp", Handler: handler},
	}

	started := make([]chan struct{}, len(servers))
	for i, server := range servers {
		ready := make(chan struct{})
		started[i] = ready
		server.NotifyStartedFunc = func() { close(ready) }
	}

	s.mu.Lock()
	s.running = servers
	s.mu.Unlock()

	wg.Go(func() {
		<-ctx.Done()
		for _, ready := range started {
			select {
			case <-ready:
			case <-time.After(startupGrace):
			}
		}
		s.mu.Lock()
		running := s.running
		s.running = nil
		s.mu.Unlock()
		for _, server := range running {
			_ = server.Shutdown()
		}
		logging.Infof("Local DNS server shut down.")
	})

	wg.Go(func() { s.sweep(ctx) })

	logging.Infof("Local DNS server listening on %s", s.opts.Addr)

	for _, server := range servers[1:] {
		wg.Go(func() {
			if err := server.ListenAndServe(); err != nil {
				logging.Infof("Local DNS server (%s) exited: %v", server.Net, err)
			}
		})
	}
	err := servers[0].ListenAndServe()
	if err != nil {
		logging.Infof("Local DNS server (%s) exited: %v", servers[0].Net, err)
	}
	return err
}

func (s *Server) sweep(ctx context.Context) {
	t := time.NewTicker(sweepInterval)
	defer t.Stop()
	for {
		select {
		case <-ctx.Done():
			return
		case now := <-t.C:
			s.cache.Sweep(now)
			if s.opts.Learner != nil {
				s.opts.Learner.Sweep(now)
			}
		}
	}
}
