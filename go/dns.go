package main

import (
	"context"

	"github.com/miekg/dns"

	"unsafie/internal/dnsproxy"
	"unsafie/internal/dnsx"
)

const proxyDNSAddr = "8.8.8.8:53"

func (e *engine) serveDNS() { _ = e.dns.Serve(e.ctx) }

func (e *engine) dnsHandler() dns.Handler { return e.dns.Handler() }

func directLookup(ctx context.Context, r *dns.Msg, qtype uint16) (*dns.Msg, error) {
	return bootstrapResolver.Race(ctx, r, func(m *dns.Msg) bool { return dnsx.Answered(m, qtype) })
}

func (e *engine) tunnelExchange(ctx context.Context, r *dns.Msg, _ uint16) (*dns.Msg, error) {
	conn, err := e.dial(ctx, "udp", proxyDNSAddr)
	if err != nil {
		return nil, err
	}
	defer conn.Close()

	if deadline, ok := ctx.Deadline(); ok {
		_ = conn.SetDeadline(deadline)
	}

	co := &dns.Conn{Conn: conn, UDPSize: dns.DefaultMsgSize}
	if err := co.WriteMsg(r); err != nil {
		return nil, err
	}
	return co.ReadMsg()
}

func newDNSProxy(e *engine) *dnsproxy.Server {
	return dnsproxy.New(dnsproxy.Options{
		Addr:    localDNSAddr,
		Rules:   rulesOrNil(e.rules),
		Peer:    edgeGroup,
		Learner: e.bypass,
		Direct:  dnsproxy.ResolverFunc(directLookup),
		Tunnel:  dnsproxy.ResolverFunc(e.tunnelExchange),
	})
}
