package resolve

import (
	"context"
	"errors"
	"net"
	"net/netip"
	"time"

	"unsafie/internal/netx"
)

const (
	DialTimeout = 10 * time.Second
	dialStagger = 250 * time.Millisecond
)

func SystemDial(ctx context.Context, network, address string) (net.Conn, error) {
	var d net.Dialer
	return d.DialContext(ctx, network, address)
}

// Dialer opens the transport to one fixed hostname. It never asks the system
// resolver for it — the answer is already known and the system resolver points
// into a tunnel that does not exist yet.
type Dialer struct {
	Group *Group
	Base  netx.DialFunc
}

func (d *Dialer) base() netx.DialFunc {
	if d.Base != nil {
		return d.Base
	}
	return SystemDial
}

func (d *Dialer) DialContext(ctx context.Context, network, address string) (net.Conn, error) {
	host, _ := netx.SplitTarget(address)
	ep := d.Group.Endpoint(host)
	if ep == nil {
		return d.base()(ctx, network, address)
	}

	targets := ep.DialTargets()
	if len(targets) == 0 {
		ep.RefreshAsync()
		conn, err := d.base()(ctx, network, address)
		if err == nil {
			if ap, perr := netip.ParseAddrPort(conn.RemoteAddr().String()); perr == nil {
				ep.Observe(ap.Addr())
			}
		}
		return conn, err
	}

	conn, err := d.race(ctx, network, ep, targets)
	if err != nil {
		ep.RefreshAsync()
	}
	return conn, err
}

// race overlaps the addresses instead of walking them. A blocked address does
// not refuse the connection, it says nothing at all, and a sequential walk
// spends the whole timeout on it while a working address sits next in the list.
func (d *Dialer) race(ctx context.Context, network string, ep *Endpoint, targets []netip.AddrPort) (net.Conn, error) {
	dialCtx, cancel := context.WithTimeout(ctx, DialTimeout)

	type attempt struct {
		idx  int
		conn net.Conn
		err  error
	}
	results := make(chan attempt, len(targets))

	started, pending := 0, 0
	launch := func() {
		idx := started
		started++
		pending++
		go func() {
			conn, err := d.base()(dialCtx, network, targets[idx].String())
			results <- attempt{idx: idx, conn: conn, err: err}
		}()
	}

	defer func() {
		cancel()
		left := pending
		go func() {
			for range left {
				if a := <-results; a.conn != nil {
					_ = a.conn.Close()
				}
			}
		}()
	}()

	stagger := time.NewTimer(dialStagger)
	defer stagger.Stop()
	launch()

	errs := make([]error, len(targets))
	for pending > 0 || started < len(targets) {
		var tick <-chan time.Time
		if started < len(targets) {
			tick = stagger.C
		}

		select {
		case <-tick:
			launch()
			stagger.Reset(dialStagger)
		case a := <-results:
			pending--
			if a.err == nil {
				ep.AdvanceDialCursorBy(a.idx)
				return a.conn, nil
			}
			errs[a.idx] = a.err
			if ctx.Err() != nil {
				return nil, ctx.Err()
			}
			if started < len(targets) {
				launch()
				if !stagger.Stop() {
					select {
					case <-stagger.C:
					default:
					}
				}
				stagger.Reset(dialStagger)
			}
		case <-ctx.Done():
			return nil, ctx.Err()
		}
	}
	ep.AdvanceDialCursor()
	return nil, firstErr(errs, errors.New("resolve: no address answered for "+ep.Host()))
}

func firstErr(errs []error, fallback error) error {
	for _, err := range errs {
		if err != nil {
			return err
		}
	}
	return fallback
}

// PacketDial hands QUIC a socket bound the same way the TCP path is: on the
// platforms that need a mark or a bound interface, an unmarked UDP socket goes
// back into the tunnel and the tunnel is what it is trying to build.
type PacketDial func(ctx context.Context, address string) (net.PacketConn, netip.AddrPort, error)
