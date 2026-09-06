//go:build linux

package tundev

import (
	"context"
	"fmt"
	"os/exec"
	"strconv"
	"sync"

	"golang.org/x/sys/unix"
	"gvisor.dev/gvisor/pkg/tcpip"
	"gvisor.dev/gvisor/pkg/tcpip/link/fdbased"
	"gvisor.dev/gvisor/pkg/tcpip/link/tun"
	"gvisor.dev/gvisor/pkg/tcpip/stack"

	"unsafie/internal/config"
	"unsafie/internal/tunnet"
)

type linuxTun struct {
	stack.LinkEndpoint

	fd     int
	closed chan struct{}
	once   sync.Once
}

func Open(ctx context.Context, cfg config.Tun, fd int) (tunnet.Device, error) {
	d := &linuxTun{closed: make(chan struct{})}

	if fd > 0 {
		dup, err := dupFD(fd)
		if err != nil {
			return nil, fmt.Errorf("dup tun fd %d: %w", fd, err)
		}
		d.fd = dup
	} else {
		opened, err := tun.Open(cfg.Iface)
		if err != nil {
			return nil, fmt.Errorf("open /dev/net/tun: %w", err)
		}
		d.fd = opened

		if err := configure(ctx, cfg); err != nil {
			_ = unix.Close(opened)
			return nil, err
		}
	}

	if err := unix.SetNonblock(d.fd, true); err != nil {
		_ = unix.Close(d.fd)
		return nil, fmt.Errorf("set tun fd non-blocking: %w", err)
	}

	ep, err := fdbased.New(&fdbased.Options{
		FDs:            []int{d.fd},
		MTU:            uint32(cfg.MTU),
		EthernetHeader: false,
		ClosedFunc:     func(tcpip.Error) { d.markDead() },
	})
	if err != nil {
		_ = unix.Close(d.fd)
		return nil, fmt.Errorf("create endpoint: %w", err)
	}
	d.LinkEndpoint = ep

	return d, nil
}

func configureSteps(cfg config.Tun) [][]string {
	return [][]string{
		{"link", "set", "dev", cfg.Iface, "mtu", strconv.Itoa(cfg.MTU)},
		{"addr", "replace", cfg.Addr4.String(), "dev", cfg.Iface},
		{"link", "set", "dev", cfg.Iface, "up"},
	}
}

func configure(ctx context.Context, cfg config.Tun) error {
	for _, args := range configureSteps(cfg) {
		out, err := exec.CommandContext(ctx, "ip", args...).CombinedOutput()
		if err != nil {
			return fmt.Errorf("ip %v: %w: %s", args, err, out)
		}
	}
	return nil
}

func (d *linuxTun) Dead() <-chan struct{} { return d.closed }

func (d *linuxTun) markDead() {
	d.once.Do(func() { close(d.closed) })
}

func (d *linuxTun) Release() {
	d.markDead()
	d.Close()
	_ = unix.Close(d.fd)
}
