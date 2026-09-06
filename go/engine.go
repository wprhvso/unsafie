package main

import (
	"context"
	"net"
	"runtime"
	"sync"
	"sync/atomic"
	"time"

	"unsafie/internal/bypass"
	"unsafie/internal/config"
	"unsafie/internal/dnsproxy"
	"unsafie/internal/fleet"
	"unsafie/internal/logging"
	"unsafie/internal/netx"
	"unsafie/internal/policy"
	"unsafie/internal/rules"
	"unsafie/internal/socksproxy"
	"unsafie/internal/tundev"
)

const bypassLearnTTL = 30 * time.Minute

var tunConfig = config.DefaultTun()

var (
	tunIface     = tunConfig.Iface
	tunGatewayIP = tunConfig.Gateway.String()
	defaultMTU   = tunConfig.MTU
)

type engine struct {
	ctx    context.Context
	cancel context.CancelFunc
	wg     sync.WaitGroup

	fd  int
	mtu int

	rules *rules.Set

	fleet *fleet.Fleet

	router *policy.Router
	bypass *bypass.Set
	dns    *dnsproxy.Server

	closeOnce sync.Once
}

var (
	current      atomic.Pointer[engine]
	lifecycleMux sync.Mutex
)

func startVpnEngine(fd, mtu int) {
	lifecycleMux.Lock()
	defer lifecycleMux.Unlock()

	shutdown(current.Swap(nil))

	if mtu <= 0 {
		mtu = defaultMTU
	}

	ctx, cancel := context.WithCancel(context.Background())
	e := newEngine(ctx, cancel, fd, mtu, ruleSet)

	if errRuleSet != nil {
		logging.Warnf("embedded rule set failed to load: %v", errRuleSet)
	} else if ruleSet != nil {
		n4, n6, ns, ne, nk := ruleSet.Stats()
		logging.Infof("Rules loaded: ipv4=%d ipv6=%d suffix=%d exact=%d keyword=%d (generated %s)",
			n4, n6, ns, ne, nk, ruleSet.Generated().UTC().Format("2006-01-02"))
	}

	current.Store(e)
	logging.Infof("Goroutines before start: %d", runtime.NumGoroutine())
	e.run()
}

func newEngine(ctx context.Context, cancel context.CancelFunc, fd, mtu int, set *rules.Set) *engine {
	e := &engine{ctx: ctx, cancel: cancel, fd: fd, mtu: mtu, rules: set}
	e.bypass = bypass.New(bypassLearnTTL)
	e.router = &policy.Router{
		TunGateway: tunGatewayIP,
		DNSPort:    localDNSPort,
		Rules:      rulesOrNil(set),
		Peer:       edgeGroup,
		Learned:    e.bypass,
	}
	e.dns = newDNSProxy(e)
	return e
}

func (e *engine) run() {
	plat.Init()

	e.wg.Go(func() { edgeGroup.Run(e.ctx) })

	e.fleet = buildFleet()
	e.wg.Go(func() { e.fleet.Run(e.ctx) })
	e.wg.Go(func() { serveStatus(e.ctx, e.fleet) })

	if ln, err := netx.Listen(e.ctx, buildSocksAddr); err != nil {
		logging.Infof("Failed to listen on %s: %v", buildSocksAddr, err)
	} else {
		proxy := socksproxy.New(e.ctx, e.dial)
		e.wg.Go(func() { proxy.Serve(ln) })
	}

	e.wg.Go(e.serveDNS)
	e.wg.Go(e.runTun)

	logging.Infof("Engine running (fd=%d mtu=%d) over %d edge(s)", e.fd, e.mtu, len(edgeGroup.Endpoints()))
}

func stopVpnEngine() {
	lifecycleMux.Lock()
	defer lifecycleMux.Unlock()

	shutdown(current.Swap(nil))
}

func shutdown(e *engine) {
	if e == nil {
		return
	}
	logging.Infof("Stopping engine; goroutines now: %d", runtime.NumGoroutine())
	e.cancel()
	e.reset()
	if e.fleet != nil {
		e.fleet.Close()
	}
	e.wg.Wait()
	e.closeTun()
	logging.Infof("Engine stopped; goroutines now: %d", runtime.NumGoroutine())
}

func (e *engine) tunCfg() config.Tun {
	cfg := tunConfig
	if e.mtu > 0 {
		cfg.MTU = e.mtu
	}
	return cfg
}

func (e *engine) reset() int {
	if e.fleet == nil {
		return 0
	}
	return e.fleet.Reset()
}

func (e *engine) closeTun() {
	if e.fd <= 0 {
		return
	}
	e.closeOnce.Do(func() {
		if err := tundev.CloseFD(e.fd); err != nil {
			logging.Infof("Closing TUN fd %d failed: %v", e.fd, err)
			return
		}
		logging.Infof("TUN fd %d closed", e.fd)
	})
}

func (e *engine) dialDirect(ctx context.Context, network, address string) (net.Conn, error) {
	return plat.DialDirect(ctx, network, address)
}

func rulesOrNil(set *rules.Set) policy.Rules {
	if set == nil {
		return nil
	}
	return set
}
