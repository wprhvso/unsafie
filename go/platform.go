package main

import (
	"context"
	"net"
)

type Platform interface {
	Init()
	DialDirect(ctx context.Context, network, address string) (net.Conn, error)
	ListenPacket(ctx context.Context) (net.PacketConn, error)
}

var plat Platform
