package resolve

import (
	"context"
	"errors"
	"net/netip"
	"slices"
	"strings"
	"sync"
)

// Group is every hostname the client is allowed to talk to directly. Routing
// and the firewall ask it the same two questions they used to ask a single
// relay: is this one of ours, and which addresses must stay reachable outside
// the tunnel. Three servers instead of one changes the answers, not the shape.
type Group struct {
	eps []*Endpoint
}

func NewGroup(hosts []string, port string, opts ...Option) *Group {
	g := &Group{}
	for _, h := range hosts {
		h = strings.TrimSpace(h)
		if h == "" {
			continue
		}
		g.eps = append(g.eps, New(h, port, opts...))
	}
	return g
}

func (g *Group) Endpoints() []*Endpoint { return g.eps }

func (g *Group) Endpoint(host string) *Endpoint {
	for _, e := range g.eps {
		if e.MatchesHost(host) {
			return e
		}
	}
	return nil
}

func (g *Group) Hosts() []string {
	out := make([]string, 0, len(g.eps))
	for _, e := range g.eps {
		out = append(out, e.Host())
	}
	return out
}

func (g *Group) MatchesHost(h string) bool {
	for _, e := range g.eps {
		if e.MatchesHost(h) {
			return true
		}
	}
	return false
}

func (g *Group) Contains(a netip.Addr) bool {
	for _, e := range g.eps {
		if e.Contains(a) {
			return true
		}
	}
	return false
}

func (g *Group) Addrs() []netip.Addr {
	var out []netip.Addr
	for _, e := range g.eps {
		for _, a := range e.Addrs() {
			if !slices.Contains(out, a) {
				out = append(out, a)
			}
		}
	}
	return out
}

func (g *Group) V4() []netip.Addr {
	var out []netip.Addr
	for _, a := range g.Addrs() {
		if a.Is4() {
			out = append(out, a)
		}
	}
	return out
}

func (g *Group) Resolved() bool {
	for _, e := range g.eps {
		if e.Resolved() {
			return true
		}
	}
	return false
}

// EnsureResolved is happy with one answer. Refusing to start until all three
// hostnames resolve would hand the censor a way to keep the client down by
// blocking the least important of them.
func (g *Group) EnsureResolved(ctx context.Context) error {
	var wg sync.WaitGroup
	errs := make([]error, len(g.eps))
	for i, e := range g.eps {
		wg.Add(1)
		go func() {
			defer wg.Done()
			errs[i] = e.EnsureResolved(ctx)
		}()
	}
	wg.Wait()

	if g.Resolved() {
		return nil
	}
	return errors.Join(errs...)
}

func (g *Group) RefreshAsync() {
	for _, e := range g.eps {
		e.RefreshAsync()
	}
}

func (g *Group) ResetThrottle() {
	for _, e := range g.eps {
		e.ResetThrottle()
	}
}

func (g *Group) SetResolver(r Resolver) {
	for _, e := range g.eps {
		e.SetResolver(r)
	}
}

func (g *Group) Run(ctx context.Context) {
	var wg sync.WaitGroup
	for _, e := range g.eps {
		wg.Add(1)
		go func() {
			defer wg.Done()
			e.Run(ctx)
		}()
	}
	wg.Wait()
}
