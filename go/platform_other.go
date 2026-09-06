//go:build !windows

package main

import (
	"context"
	"net"
)

type basePlatform struct{}

func (basePlatform) Init() {}

func (basePlatform) DialDirect(ctx context.Context, network, address string) (net.Conn, error) {
	var d net.Dialer
	return d.DialContext(ctx, network, address)
}

func (basePlatform) ListenPacket(ctx context.Context) (net.PacketConn, error) {
	var lc net.ListenConfig
	return lc.ListenPacket(ctx, "udp", ":0")
}
