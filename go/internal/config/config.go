package config

import "net/netip"

type Tun struct {
	Iface   string
	Gateway netip.Addr
	Addr4   netip.Prefix
	MTU     int
}

func DefaultTun() Tun {
	return Tun{
		Iface:   "unsafie0",
		Gateway: netip.MustParseAddr("10.0.0.1"),
		Addr4:   netip.MustParsePrefix("10.0.0.2/24"),
		MTU:     1400,
	}
}

type BypassPrefix struct {
	Prefix netip.Prefix
	OnLink bool
}

var Bypass = []BypassPrefix{
	{Prefix: netip.MustParsePrefix("10.0.0.0/8")},
	{Prefix: netip.MustParsePrefix("172.16.0.0/12")},
	{Prefix: netip.MustParsePrefix("192.168.0.0/16")},
	{Prefix: netip.MustParsePrefix("100.64.0.0/10")},
	{Prefix: netip.MustParsePrefix("169.254.0.0/16"), OnLink: true},
}

func BypassCIDRs() []string {
	out := make([]string, 0, len(Bypass))
	for _, b := range Bypass {
		out = append(out, b.Prefix.String())
	}
	return out
}

var SplitDefaults = []netip.Prefix{
	netip.MustParsePrefix("0.0.0.0/1"),
	netip.MustParsePrefix("128.0.0.0/1"),
}

const (
	FwMark    = 1
	FwMarkHex = "0x1"
)
