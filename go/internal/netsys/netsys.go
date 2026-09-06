package netsys

import (
	"context"
	"net/netip"
)

type Peer interface {
	Addrs() []netip.Addr
	V4() []netip.Addr
	Contains(addr netip.Addr) bool
	EnsureResolved(ctx context.Context) error
	RefreshAsync()
}
