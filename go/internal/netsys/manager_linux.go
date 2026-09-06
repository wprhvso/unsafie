//go:build linux && !android

package netsys

import (
	"context"
	"net"
	"sync"
	"sync/atomic"
	"time"

	"unsafie/internal/config"
	"unsafie/internal/logging"
	"unsafie/internal/sysexec"
)

type Manager struct {
	cfg  config.Tun
	peer Peer
	sys  sysexec.Runner

	ctx context.Context

	stateFile    string
	pollInterval time.Duration
	tunnelPoll   time.Duration
	ifaceByName  func(string) (*net.Interface, error)

	onRoutesReset func() int

	edgeRoutesMu   sync.Mutex
	edgeRoutesLive map[string]edgeRoute
	routesFrozen   atomic.Bool
	warnEdgeV6Once sync.Once

	uplinkMu          sync.Mutex
	uplinkGateway     string
	uplinkIface       string
	warnTunUplinkOnce sync.Once
}

type Option func(*Manager)

func WithRunner(r sysexec.Runner) Option { return func(m *Manager) { m.sys = r } }

func WithStateFile(path string) Option { return func(m *Manager) { m.stateFile = path } }

func WithResetHook(f func() int) Option { return func(m *Manager) { m.onRoutesReset = f } }

func New(cfg config.Tun, peer Peer, opts ...Option) *Manager {
	m := &Manager{
		cfg:            cfg,
		peer:           peer,
		sys:            sysexec.New(),
		ctx:            context.Background(),
		stateFile:      "/run/unsafie/edge-routes",
		pollInterval:   20 * time.Second,
		tunnelPoll:     100 * time.Millisecond,
		ifaceByName:    net.InterfaceByName,
		onRoutesReset:  func() int { return 0 },
		edgeRoutesLive: map[string]edgeRoute{},
	}
	for _, opt := range opts {
		opt(m)
	}
	return m
}

func (m *Manager) Prepare() (gateway, iface string, err error) {
	m.cleanupLegacyRules()

	gateway, iface, err = m.detectNetwork()
	if err != nil {
		return "", "", err
	}
	m.setUplink(gateway, iface)
	m.cleanupLegacyBypassRoutes(gateway, iface)
	m.loadEdgeRouteState()
	return gateway, iface, nil
}

func (m *Manager) Apply(gateway, iface string) { m.applyUplink(gateway, iface) }

func (m *Manager) Watch(stop <-chan struct{}) { m.watchUplink(stop) }

func (m *Manager) AwaitTunnel(stop <-chan struct{}) { m.waitForTunnel(stop) }

func (m *Manager) SyncEdgeRoutes() { m.syncEdgeRoutes(m.currentUplink()) }

func (m *Manager) Teardown() {
	m.routesFrozen.Store(true)

	m.delRule("pref", rulePrefTun, "table", tunTable)
	m.delRule("pref", rulePrefMain, "table", "main", "suppress_prefixlength", "0")
	m.delRule("pref", rulePrefMark, "fwmark", fwmark, "table", physTable)
	m.sys.Try(m.ctx, "resolvectl", "revert", m.cfg.Iface)

	m.unblockIPv6()
	m.removeEdgeRoutes()

	_, lastIface := m.currentUplink()
	m.removeFirewall(lastIface)

	m.sys.Try(m.ctx, "ip", "route", "flush", "table", tunTable)
	m.sys.Try(m.ctx, "ip", "route", "flush", "table", physTable)

	logging.Infof("Cleanup complete.")
}
