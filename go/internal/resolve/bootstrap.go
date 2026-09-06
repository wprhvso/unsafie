package resolve

import (
	"context"
	"errors"
	"net/netip"
	"time"

	"github.com/miekg/dns"

	"unsafie/internal/dnsx"
	"unsafie/internal/netx"
)

func clampTTL(ttl time.Duration) time.Duration {
	return min(max(ttl, ttlFloor), TTLCeiling)
}

// BootstrapResolver finds the fixed hostnames without going through the tunnel,
// because until it answers there is no tunnel to go through and the system
// resolver is already pointed inside one.
type BootstrapResolver struct {
	Servers []string
	Dial    netx.DialFunc
	Timeout time.Duration
}

func (r BootstrapResolver) servers() []string {
	if len(r.Servers) == 0 {
		return defaultBootstrap
	}
	return r.Servers
}

func (r BootstrapResolver) timeout() time.Duration {
	if r.Timeout <= 0 {
		return DNSTimeout
	}
	return r.Timeout
}

func (r BootstrapResolver) Race(ctx context.Context, msg *dns.Msg, good func(*dns.Msg) bool) (*dns.Msg, error) {
	return dnsx.Race(ctx, msg, r.servers(), r.Dial, r.timeout(), good)
}

func (r BootstrapResolver) Resolve(ctx context.Context, host string) ([]netip.Addr, time.Duration, error) {
	msg := new(dns.Msg)
	msg.SetQuestion(dns.Fqdn(host), dns.TypeA)
	msg.RecursionDesired = true

	resp, err := r.Race(ctx, msg, func(m *dns.Msg) bool {
		if m.Rcode != dns.RcodeSuccess {
			return false
		}
		addrs, _ := dnsx.AddrsFromAnswer(m.Answer, TTLCeiling)
		return len(filterAddrs(addrs)) > 0
	})
	if err != nil {
		return nil, 0, err
	}

	addrs, ttl := dnsx.AddrsFromAnswer(resp.Answer, TTLCeiling)
	addrs = filterAddrs(addrs)
	if len(addrs) == 0 {
		return nil, 0, errors.New("no usable address for " + host)
	}
	return addrs, clampTTL(ttl), nil
}
