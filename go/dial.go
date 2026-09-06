package main

import (
	"context"
	"net"
	"strings"

	"unsafie/internal/logging"
	"unsafie/internal/policy"
)

func (e *engine) dial(ctx context.Context, network, address string) (net.Conn, error) {
	switch d := e.decide(address); d.Route {
	case policy.RouteDNS:
		var dialer net.Dialer
		return dialer.DialContext(ctx, dnsNetwork(network), localDNSAddr)
	case policy.RouteDirect:
		logging.Infof("[%s] direct %s (%s)", network, address, d.Reason)
		return e.dialDirect(ctx, network, address)
	default:
		return e.fleet.Dial(ctx, network, address)
	}
}

func dnsNetwork(network string) string {
	if strings.HasPrefix(network, "tcp") {
		return "tcp"
	}
	return "udp"
}
