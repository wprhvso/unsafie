//go:build linux && !android

package main

import (
	"context"
	"net"
	"syscall"

	"golang.org/x/sys/unix"

	"unsafie/internal/config"
)

func markSocket(_, _ string, c syscall.RawConn) error {
	var serr error
	if err := c.Control(func(fd uintptr) {
		serr = unix.SetsockoptInt(int(fd), unix.SOL_SOCKET, unix.SO_MARK, config.FwMark)
	}); err != nil {
		return err
	}
	return serr
}

func (linuxPlatform) DialDirect(ctx context.Context, network, address string) (net.Conn, error) {
	d := net.Dialer{Control: markSocket}
	return d.DialContext(ctx, network, address)
}

func (linuxPlatform) ListenPacket(ctx context.Context) (net.PacketConn, error) {
	lc := net.ListenConfig{Control: markSocket}
	return lc.ListenPacket(ctx, "udp", ":0")
}
