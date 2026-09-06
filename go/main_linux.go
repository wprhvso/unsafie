//go:build linux && !android

package main

import (
	"context"
	"os"
	"os/exec"
	"os/signal"
	"strings"
	"syscall"
	"time"

	"unsafie/internal/chrome"
	"unsafie/internal/logging"
	"unsafie/internal/netsys"
)

type linuxPlatform struct{ basePlatform }

func init() {
	logging.SetDefault(logging.NewWriter(os.Stdout))
	plat = linuxPlatform{}
}

const edgeResolveTimeout = 8 * time.Second

func main() {
	if os.Getenv("GODEBUG") != "netdns=go" {
		os.Setenv("GODEBUG", "netdns=go")
		if argv0, err := exec.LookPath(os.Args[0]); err == nil {
			logging.Infof("Re-executing with GODEBUG=netdns=go...")
			_ = syscall.Exec(argv0, os.Args, os.Environ()) //nolint:gosec // re-exec of self with our own argv
		}
	}

	logging.Infof("unsafie %s, %s", buildVersion, chrome.Chrome131.Fingerprint())
	logging.Infof("Setting effective Group ID to 10001 for policy routing...")
	if err := syscall.Setresgid(10001, 10001, 10001); err != nil {
		logging.Infof("Failed to set GID to 10001: %v. Run as root.", err)
		os.Exit(1)
	}

	net := netsys.New(tunConfig, edgeGroup, netsys.WithResetHook(resetEdgeSessions))

	gateway, iface, err := net.Prepare()
	if err != nil {
		logging.Errorf("failed to detect network gateway: %v", err)
		os.Exit(1)
	}
	logging.Infof("Detected physical uplink: %s via %s", iface, gateway)

	if servers := uplinkResolvers(iface, gateway); len(servers) > 0 {
		logging.Infof("Bootstrap resolvers: %s", strings.Join(servers, ", "))
		bootstrapResolver.Servers = servers
		edgeGroup.SetResolver(bootstrapResolver)
	}

	resolveCtx, cancelResolve := context.WithTimeout(context.Background(), edgeResolveTimeout)
	if err := edgeGroup.EnsureResolved(resolveCtx); err != nil {
		logging.Warnf("no edge hostname resolved yet: %v", err)
	}
	cancelResolve()

	setEdgeChangeHook(net.SyncEdgeRoutes)
	net.Apply(gateway, iface)

	stop := make(chan struct{})
	go net.AwaitTunnel(stop)
	go net.Watch(stop)

	sigs := make(chan os.Signal, 1)
	signal.Notify(sigs, syscall.SIGINT, syscall.SIGTERM)

	go startVpnEngine(0, defaultMTU)

	sig := <-sigs
	logging.Infof("Received signal: %v. Cleaning up...", sig)

	close(stop)
	setEdgeChangeHook(nil)

	stopVpnEngine()
	net.Teardown()

	os.Exit(0)
}
