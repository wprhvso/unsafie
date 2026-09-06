package resolve

import (
	"context"
	"errors"
	"fmt"
	"net"
	"net/netip"
	"slices"
	"strconv"
	"strings"
	"sync"
	"sync/atomic"
	"time"

	"unsafie/internal/logging"
)

const (
	refreshMinInterval = 10 * time.Second
	refreshMaxInterval = 5 * time.Minute
	DNSTimeout         = 4 * time.Second
	ttlFloor           = 30 * time.Second
	TTLCeiling         = 30 * time.Minute
	observedCap        = 4
)

var defaultBootstrap = []string{"1.1.1.1:53", "8.8.8.8:53", "9.9.9.9:53"}

var (
	ErrResolveInFlight = errors.New("resolve: already in progress")
	ErrNoPlatform      = errors.New("resolve: platform not initialised")
)

type addrSet struct {
	list    []netip.Addr
	expires time.Time
}

// Endpoint is one of the fixed hostnames the client is built with. It resolves
// outside the tunnel, remembers the addresses that actually worked, and never
// forgets the last good answer just because the current one failed: a client
// whose DNS was taken away is exactly the client that still needs to connect.
type Endpoint struct {
	host      string
	port      string
	portNum   uint16
	isLiteral bool

	cur  atomic.Pointer[addrSet]
	next atomic.Uint32

	mu       sync.Mutex
	resolved []netip.Addr
	observed []netip.Addr
	lastTry  time.Time
	lastErr  error
	inflight bool

	resolver   Resolver
	onChange   ChangeFunc
	minRefresh time.Duration
}

type Resolver interface {
	Resolve(ctx context.Context, host string) ([]netip.Addr, time.Duration, error)
}

type ResolverFunc func(ctx context.Context, host string) ([]netip.Addr, time.Duration, error)

func (f ResolverFunc) Resolve(ctx context.Context, host string) ([]netip.Addr, time.Duration, error) {
	return f(ctx, host)
}

type ChangeFunc func(replaced bool)

type Option func(*Endpoint)

func WithResolver(res Resolver) Option { return func(e *Endpoint) { e.resolver = res } }

func WithOnChange(f ChangeFunc) Option { return func(e *Endpoint) { e.onChange = f } }

func WithMinRefreshInterval(d time.Duration) Option {
	return func(e *Endpoint) { e.minRefresh = d }
}

func New(host, port string, opts ...Option) *Endpoint {
	r := &Endpoint{
		host:       strings.TrimSuffix(host, "."),
		port:       port,
		minRefresh: refreshMinInterval,
	}
	for _, opt := range opts {
		opt(r)
	}
	if n, err := strconv.ParseUint(port, 10, 16); err == nil {
		r.portNum = uint16(n)
	}

	snap := &addrSet{}
	if addr, err := netip.ParseAddr(r.host); err == nil {
		r.isLiteral = true
		if a := addr.Unmap(); usableAddr(a) {
			snap.list = []netip.Addr{a}
			r.resolved = []netip.Addr{a}
		}
	}
	r.cur.Store(snap)
	return r
}

func usableAddr(a netip.Addr) bool {
	a = a.Unmap()
	if !a.IsValid() {
		return false
	}
	switch {
	case a.IsLoopback(), a.IsUnspecified(), a.IsMulticast(),
		a.IsLinkLocalUnicast(), a.IsLinkLocalMulticast(),
		a.IsInterfaceLocalMulticast():
		return false
	}
	return true
}

func filterAddrs(in []netip.Addr) []netip.Addr {
	out := make([]netip.Addr, 0, len(in))
	seen := make(map[netip.Addr]struct{}, len(in))
	for _, a := range in {
		a = a.Unmap()
		if !usableAddr(a) {
			continue
		}
		if _, dup := seen[a]; dup {
			continue
		}
		seen[a] = struct{}{}
		out = append(out, a)
	}
	return out
}

func (r *Endpoint) Host() string { return r.host }

func (r *Endpoint) Port() string { return r.port }

func (r *Endpoint) Addr() string { return net.JoinHostPort(r.host, r.port) }

func (r *Endpoint) IsLiteral() bool { return r.isLiteral }

func (r *Endpoint) Addrs() []netip.Addr { return r.cur.Load().list }

func (r *Endpoint) Resolved() bool { return len(r.cur.Load().list) > 0 }

func (r *Endpoint) Contains(a netip.Addr) bool {
	return slices.Contains(r.cur.Load().list, a.Unmap())
}

func (r *Endpoint) MatchesHost(h string) bool {
	if r.host == "" {
		return false
	}
	return strings.EqualFold(strings.TrimSuffix(h, "."), r.host)
}

func (r *Endpoint) V4() []netip.Addr {
	list := r.cur.Load().list
	out := make([]netip.Addr, 0, len(list))
	for _, a := range list {
		if a.Is4() {
			out = append(out, a)
		}
	}
	return out
}

func (r *Endpoint) DialTargets() []netip.AddrPort {
	list := r.cur.Load().list
	n := len(list)
	if n == 0 {
		return nil
	}
	start := int(r.next.Load() % uint32(n))
	out := make([]netip.AddrPort, 0, n)
	for i := range n {
		out = append(out, netip.AddrPortFrom(list[(start+i)%n], r.portNum))
	}
	return out
}

func (r *Endpoint) AdvanceDialCursor() { r.AdvanceDialCursorBy(1) }

func (r *Endpoint) AdvanceDialCursorBy(n int) {
	if n > 0 {
		r.next.Add(uint32(n))
	}
}

func (r *Endpoint) TCPAddr() *net.TCPAddr {
	if list := r.cur.Load().list; len(list) > 0 {
		return net.TCPAddrFromAddrPort(netip.AddrPortFrom(list[0], r.portNum))
	}
	return &net.TCPAddr{Port: int(r.portNum)}
}

func (r *Endpoint) SetResolver(res Resolver) {
	r.mu.Lock()
	r.resolver = res
	r.mu.Unlock()
}

func (r *Endpoint) ResetThrottle() {
	r.mu.Lock()
	r.lastTry = time.Time{}
	r.mu.Unlock()
}

func (r *Endpoint) Refresh(ctx context.Context) error {
	if r.isLiteral {
		return nil
	}

	r.mu.Lock()
	if r.inflight {
		r.mu.Unlock()
		return ErrResolveInFlight
	}
	if !r.lastTry.IsZero() && time.Since(r.lastTry) < r.minRefresh {
		cached := r.lastErr
		r.mu.Unlock()
		return cached
	}
	r.inflight = true
	r.lastTry = time.Now()
	resolver := r.resolver
	r.mu.Unlock()

	if resolver == nil {
		return errors.New("resolve: no resolver configured")
	}
	addrs, ttl, err := resolver.Resolve(ctx, r.host)

	r.mu.Lock()
	r.inflight = false

	if err == nil {
		addrs = filterAddrs(addrs)
		if len(addrs) == 0 {
			err = fmt.Errorf("no usable address for %s", r.host)
		}
	}
	if err != nil {
		repeat := r.lastErr != nil && r.lastErr.Error() == err.Error()
		r.lastErr = err
		known := len(r.cur.Load().list)
		r.mu.Unlock()
		if !repeat {
			logging.Infof("Endpoint %s: resolve failed: %v (keeping %d known address(es))", r.host, err, known)
		}
		return err
	}

	r.lastErr = nil
	prev := r.cur.Load().list
	r.resolved = addrs
	snap := r.rebuildLocked(time.Now().Add(clampTTL(ttl)))
	r.cur.Store(snap)
	r.mu.Unlock()

	if sameAddrs(prev, snap.list) {
		return nil
	}

	logging.Infof("Endpoint %s resolved to %s", r.host, joinAddrs(snap.list))
	if r.onChange != nil {
		r.onChange(len(prev) > 0 && disjointAddrs(prev, snap.list))
	}
	return nil
}

func (r *Endpoint) RefreshAsync() {
	if r.isLiteral {
		return
	}
	go func() {
		ctx, cancel := context.WithTimeout(context.Background(), 2*DNSTimeout)
		defer cancel()
		_ = r.Refresh(ctx)
	}()
}

func (r *Endpoint) EnsureResolved(ctx context.Context) error {
	if r.isLiteral {
		return nil
	}
	if s := r.cur.Load(); len(s.list) > 0 && (s.expires.IsZero() || time.Now().Before(s.expires)) {
		return nil
	}
	return r.Refresh(ctx)
}

func (r *Endpoint) Observe(a netip.Addr) {
	a = a.Unmap()
	if r.isLiteral || !usableAddr(a) {
		return
	}

	r.mu.Lock()
	if slices.Contains(r.resolved, a) || slices.Contains(r.observed, a) {
		r.mu.Unlock()
		return
	}
	r.observed = append(r.observed, a)
	if len(r.observed) > observedCap {
		r.observed = append([]netip.Addr(nil), r.observed[len(r.observed)-observedCap:]...)
	}
	snap := r.rebuildLocked(r.cur.Load().expires)
	r.cur.Store(snap)
	r.mu.Unlock()

	logging.Infof("Endpoint %s: learned address %s from a working connection.", r.host, a)
	if r.onChange != nil {
		r.onChange(false)
	}
}

func (r *Endpoint) Run(ctx context.Context) {
	if r.isLiteral {
		return
	}

	_ = r.Refresh(ctx)

	t := time.NewTimer(r.nextRefreshIn())
	defer t.Stop()
	for {
		select {
		case <-ctx.Done():
			return
		case <-t.C:
		}
		_ = r.Refresh(ctx)
		t.Reset(r.nextRefreshIn())
	}
}

func (r *Endpoint) nextRefreshIn() time.Duration {
	s := r.cur.Load()
	if len(s.list) == 0 || s.expires.IsZero() {
		return ttlFloor
	}
	return min(max(time.Until(s.expires), ttlFloor), refreshMaxInterval)
}

func (r *Endpoint) rebuildLocked(expires time.Time) *addrSet {
	list := make([]netip.Addr, 0, len(r.resolved)+len(r.observed))
	seen := make(map[netip.Addr]struct{}, len(r.resolved)+len(r.observed))
	add := func(a netip.Addr) {
		if _, dup := seen[a]; dup {
			return
		}
		seen[a] = struct{}{}
		list = append(list, a)
	}
	for _, src := range [][]netip.Addr{r.resolved, r.observed} {
		for _, a := range src {
			if a.Is4() {
				add(a)
			}
		}
	}
	for _, src := range [][]netip.Addr{r.resolved, r.observed} {
		for _, a := range src {
			if !a.Is4() {
				add(a)
			}
		}
	}
	return &addrSet{list: list, expires: expires}
}

func sameAddrs(a, b []netip.Addr) bool {
	return slices.Equal(a, b)
}

func disjointAddrs(a, b []netip.Addr) bool {
	for _, x := range a {
		if slices.Contains(b, x) {
			return false
		}
	}
	return true
}

func joinAddrs(addrs []netip.Addr) string {
	if len(addrs) == 0 {
		return "(none)"
	}
	parts := make([]string, 0, len(addrs))
	for _, a := range addrs {
		parts = append(parts, a.String())
	}
	return strings.Join(parts, ", ")
}
