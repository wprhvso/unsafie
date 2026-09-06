package dnsx

import (
	"context"
	"errors"
	"fmt"
	"net/netip"
	"time"

	"github.com/miekg/dns"

	"unsafie/internal/netx"
)

var ErrNoResolvers = errors.New("dnsx: no resolver configured")

func Race(
	ctx context.Context,
	msg *dns.Msg,
	servers []string,
	dial netx.DialFunc,
	timeout time.Duration,
	good func(*dns.Msg) bool,
) (*dns.Msg, error) {
	if len(servers) == 0 {
		return nil, ErrNoResolvers
	}

	ctx, cancel := context.WithCancel(ctx)
	defer cancel()

	type reply struct {
		server string
		msg    *dns.Msg
		err    error
	}
	replies := make(chan reply, len(servers))
	for _, ns := range servers {
		go func() {
			resp, err := Exchange(ctx, msg.Copy(), ns, dial, timeout)
			replies <- reply{server: ns, msg: resp, err: err}
		}()
	}

	var (
		fallback *dns.Msg
		errs     []error
	)
	for range servers {
		r := <-replies
		switch {
		case r.err != nil:
			errs = append(errs, fmt.Errorf("%s: %w", r.server, r.err))
		case r.msg == nil:
			errs = append(errs, fmt.Errorf("%s: empty reply", r.server))
		case good == nil || good(r.msg):
			return r.msg, nil
		default:
			if fallback == nil {
				fallback = r.msg
			}
			errs = append(errs, fmt.Errorf("%s: %s", r.server, dns.RcodeToString[r.msg.Rcode]))
		}
	}
	if fallback != nil {
		return fallback, nil
	}
	return nil, errors.Join(errs...)
}

func Exchange(
	ctx context.Context,
	msg *dns.Msg,
	server string,
	dial netx.DialFunc,
	timeout time.Duration,
) (*dns.Msg, error) {
	if dial == nil {
		return nil, errors.New("dnsx: no dialer")
	}

	c, err := dial(ctx, "udp", server)
	if err != nil {
		return nil, err
	}
	defer c.Close()

	deadline := time.Now().Add(timeout)
	if d, ok := ctx.Deadline(); ok && d.Before(deadline) {
		deadline = d
	}
	_ = c.SetDeadline(deadline)

	stop := make(chan struct{})
	defer close(stop)
	go func() {
		select {
		case <-ctx.Done():
			_ = c.SetDeadline(time.Now())
		case <-stop:
		}
	}()

	resp, _, err := (&dns.Client{}).ExchangeWithConn(msg, &dns.Conn{Conn: c})
	return resp, err
}

func AddrsFromAnswer(answer []dns.RR, ceiling time.Duration) ([]netip.Addr, time.Duration) {
	var addrs []netip.Addr
	ttl := ceiling
	for _, rr := range answer {
		a, ok := rr.(*dns.A)
		if !ok {
			continue
		}
		addr, ok := netip.AddrFromSlice(a.A.To4())
		if !ok {
			continue
		}
		addrs = append(addrs, addr.Unmap())
		if d := time.Duration(a.Hdr.Ttl) * time.Second; d < ttl {
			ttl = d
		}
	}
	return addrs, ttl
}

func Answered(msg *dns.Msg, qtype uint16) bool {
	if msg == nil {
		return false
	}
	if msg.Rcode == dns.RcodeNameError {
		return true
	}
	if msg.Rcode != dns.RcodeSuccess {
		return false
	}
	for _, rr := range msg.Answer {
		if rr.Header().Rrtype == qtype {
			return true
		}
	}
	return false
}
