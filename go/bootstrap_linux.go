//go:build linux && !android

package main

import (
	"context"
	"net"
	"net/netip"
	"os/exec"
	"strings"
	"time"
)

const resolvectlTimeout = 3 * time.Second

func uplinkResolvers(iface, gateway string) []string {
	var out []string
	for _, addr := range resolvectlDNS(iface) {
		out = append(out, net.JoinHostPort(addr, "53"))
	}
	if len(out) == 0 && gateway != "" {
		out = append(out, net.JoinHostPort(gateway, "53"))
	}
	return out
}

func resolvectlDNS(iface string) []string {
	if iface == "" {
		return nil
	}

	ctx, cancel := context.WithTimeout(context.Background(), resolvectlTimeout)
	defer cancel()

	raw, err := exec.CommandContext(ctx, "resolvectl", "dns", iface).Output()
	if err != nil {
		return nil
	}

	_, list, ok := strings.Cut(string(raw), ":")
	if !ok {
		return nil
	}

	var out []string
	for _, field := range strings.Fields(list) {
		addr, err := netip.ParseAddr(field)
		if err != nil || !addr.Is4() || addr.IsLoopback() {
			continue
		}
		out = append(out, addr.String())
	}
	return out
}
