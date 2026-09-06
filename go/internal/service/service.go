package service

import (
	"net/netip"
	"strings"

	"golang.org/x/net/publicsuffix"
)

// Key names the thing a decision is actually about. Not the host: "s3.eu-central-1.amazonaws.com"
// and "s3.us-east-1.amazonaws.com" fail and recover together, and treating them
// as two unrelated arms would take twice as long to learn the same fact. Not
// the whole destination address either: one flaky host inside a CDN should not
// condemn the CDN.
//
// For names that is the registrable domain. For literal addresses it is the /24
// or the /48 the address falls in, which is as close to "one operator" as an
// address gets without asking anybody.
func Key(host string) string {
	host = strings.TrimSuffix(strings.ToLower(strings.Trim(host, "[]")), ".")
	if host == "" {
		return "?"
	}
	if addr, err := netip.ParseAddr(host); err == nil {
		return prefixKey(addr)
	}
	if etld, err := publicsuffix.EffectiveTLDPlusOne(host); err == nil && etld != "" {
		return etld
	}
	return host
}

func prefixKey(addr netip.Addr) string {
	addr = addr.Unmap()
	bits := 48
	if addr.Is4() {
		bits = 24
	}
	p, err := addr.Prefix(bits)
	if err != nil {
		return addr.String()
	}
	return p.String()
}
