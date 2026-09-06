package policy

import (
	"net/netip"

	"unsafie/internal/netx"
)

type Route int

const (
	RouteTunnel Route = iota
	RouteDirect
	RouteDNS
)

func (r Route) String() string {
	switch r {
	case RouteDirect:
		return "direct"
	case RouteDNS:
		return "dns"
	default:
		return "tunnel"
	}
}

type Decision struct {
	Route  Route
	Reason string
}

type Rules interface {
	LookupDomain(host string) bool
	LookupIP(addr netip.Addr) bool
}

type Peer interface {
	MatchesHost(host string) bool
	Contains(addr netip.Addr) bool
}

type Learned interface {
	Has(addr netip.Addr) bool
}

var cgnatPrefix = netip.MustParsePrefix("100.64.0.0/10")

var bypassPorts = map[string]bool{
	"22":   true,
	"123":  true,
	"4460": true,
}

type Router struct {
	TunGateway string
	DNSPort    string

	Rules   Rules
	Peer    Peer
	Learned Learned
}

func (r *Router) Decide(address string) Decision {
	host, port := netx.SplitTarget(address)

	if host == r.TunGateway && port == r.DNSPort {
		return Decision{RouteDNS, "dns-redirect"}
	}

	addr, err := netip.ParseAddr(host)
	if err != nil {
		if r.Peer != nil && r.Peer.MatchesHost(host) {
			return Decision{RouteDirect, "edge"}
		}
		if r.Rules != nil && r.Rules.LookupDomain(host) {
			return Decision{RouteDirect, "domain"}
		}
		return Decision{RouteTunnel, "default"}
	}

	if addr.Is4In6() {
		addr = addr.Unmap()
	}

	if r.Peer != nil && r.Peer.Contains(addr) {
		return Decision{RouteDirect, "edge"}
	}

	switch {
	case addr.IsLoopback(), addr.IsPrivate(), addr.IsLinkLocalUnicast(),
		addr.IsLinkLocalMulticast(), addr.IsMulticast(), addr.IsUnspecified():
		return Decision{RouteDirect, "local"}
	}

	if addr.Is4() && cgnatPrefix.Contains(addr) {
		return Decision{RouteDirect, "cgnat"}
	}

	if bypassPorts[port] {
		return Decision{RouteDirect, "port"}
	}

	if r.Learned != nil && r.Learned.Has(addr) {
		return Decision{RouteDirect, "learned"}
	}

	if r.Rules != nil && r.Rules.LookupIP(addr) {
		return Decision{RouteDirect, "geoip"}
	}

	return Decision{RouteTunnel, "default"}
}
