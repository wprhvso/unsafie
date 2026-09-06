//go:build linux && !android

package netsys

import (
	"fmt"
	"net"
	"net/netip"
	"os"
	"path/filepath"
	"sort"
	"strconv"
	"strings"
	"time"

	"unsafie/internal/config"
	"unsafie/internal/logging"
)

const (
	fwmark = config.FwMarkHex

	physTable = "100"
	tunTable  = "200"

	rulePrefMark = "100"
	rulePrefMain = "110"
	rulePrefTun  = "120"
)

type edgeRoute struct {
	gateway string
	iface   string
}

func (m *Manager) tunnelAsUplink(iface string) bool {
	if iface != m.cfg.Iface {
		return false
	}
	m.warnTunUplinkOnce.Do(func() {
		logging.Infof("Refusing to program %s as the uplink; keeping the physical one.", m.cfg.Iface)
	})
	return true
}

func (m *Manager) currentUplink() (gateway, iface string) {
	m.uplinkMu.Lock()
	defer m.uplinkMu.Unlock()
	return m.uplinkGateway, m.uplinkIface
}

func (m *Manager) setUplink(gateway, iface string) bool {
	m.uplinkMu.Lock()
	defer m.uplinkMu.Unlock()
	if m.uplinkGateway == gateway && m.uplinkIface == iface {
		return false
	}
	m.uplinkGateway, m.uplinkIface = gateway, iface
	return true
}

func viaArgs(gateway, iface string) []string {
	if gateway == "" {
		return []string{"dev", iface}
	}
	return []string{"via", gateway, "dev", iface}
}

func (m *Manager) loadEdgeRouteState() {
	data, err := os.ReadFile(m.stateFile)
	if err != nil {
		return
	}

	m.edgeRoutesMu.Lock()
	defer m.edgeRoutesMu.Unlock()

	for line := range strings.SplitSeq(string(data), "\n") {
		fields := strings.Fields(line)
		if len(fields) == 0 {
			continue
		}
		route := edgeRoute{}
		if len(fields) >= 3 {
			route.gateway, route.iface = fields[1], fields[2]
			if route.gateway == "-" {
				route.gateway = ""
			}
		}
		m.edgeRoutesLive[fields[0]] = route
	}
	if len(m.edgeRoutesLive) > 0 {
		logging.Infof("Recovered %d edge bypass route(s) from %s.", len(m.edgeRoutesLive), m.stateFile)
	}
}

func (m *Manager) saveEdgeRouteStateLocked() {
	if len(m.edgeRoutesLive) == 0 {
		if err := os.Remove(m.stateFile); err != nil && !os.IsNotExist(err) {
			logging.Warnf("failed to clear %s: %v", m.stateFile, err)
		}
		return
	}

	lines := make([]string, 0, len(m.edgeRoutesLive))
	for cidr, route := range m.edgeRoutesLive {
		gateway := route.gateway
		if gateway == "" {
			gateway = "-"
		}
		lines = append(lines, cidr+" "+gateway+" "+route.iface)
	}
	sort.Strings(lines)

	if err := os.MkdirAll(filepath.Dir(m.stateFile), 0o755); err != nil {
		logging.Warnf("failed to create %s: %v", filepath.Dir(m.stateFile), err)
		return
	}
	if err := os.WriteFile(m.stateFile, []byte(strings.Join(lines, "\n")+"\n"), 0o644); err != nil {
		logging.Warnf("failed to write %s: %v", m.stateFile, err)
	}
}

func (m *Manager) deleteEdgeRouteLocked(cidr string, route edgeRoute) bool {
	args := []string{"route", "del", cidr}
	if route.iface != "" {
		args = append(args, viaArgs(route.gateway, route.iface)...)
	}
	if err := m.sys.Run(m.ctx, "ip", args...); err != nil {
		logging.Warnf("failed to remove edge bypass route %s: %v", cidr, err)
		return false
	}
	delete(m.edgeRoutesLive, cidr)
	return true
}

func (m *Manager) syncEdgeRoutes(gateway, iface string) {
	if iface == "" || m.tunnelAsUplink(iface) || m.routesFrozen.Load() {
		return
	}

	m.edgeRoutesMu.Lock()
	defer m.edgeRoutesMu.Unlock()

	want := make(map[string]bool)
	for _, a := range m.peer.Addrs() {
		if !a.Is4() {
			m.warnEdgeV6Once.Do(func() {
				logging.Infof("Edge address %s is IPv6; no bypass route programmed (the Linux path is IPv4-only).", a)
			})
			continue
		}
		want[netip.PrefixFrom(a, 32).String()] = true
	}

	changed := false
	for cidr, route := range m.edgeRoutesLive {
		if want[cidr] && route.gateway == gateway && route.iface == iface {
			continue
		}
		if !m.deleteEdgeRouteLocked(cidr, route) {
			continue
		}
		logging.Infof("Edge bypass route removed: %s", cidr)
		changed = true
	}

	for cidr := range want {
		if _, live := m.edgeRoutesLive[cidr]; live {
			continue
		}
		args := append([]string{"route", "replace", cidr}, viaArgs(gateway, iface)...)
		if err := m.sys.Run(m.ctx, "ip", args...); err != nil {
			logging.Warnf("failed to add edge bypass route %s via %s dev %s: %v", cidr, gateway, iface, err)
			continue
		}
		m.edgeRoutesLive[cidr] = edgeRoute{gateway: gateway, iface: iface}
		changed = true
		logging.Infof("Edge bypass route added: %s -> %s (%s)", cidr, gateway, iface)
	}

	if changed {
		m.saveEdgeRouteStateLocked()
	}
}

func (m *Manager) removeEdgeRoutes() {
	m.edgeRoutesMu.Lock()
	defer m.edgeRoutesMu.Unlock()

	for cidr, route := range m.edgeRoutesLive {
		m.deleteEdgeRouteLocked(cidr, route)
	}
	m.saveEdgeRouteStateLocked()
}

func (m *Manager) routeGet() ([]byte, error) {
	return m.sys.Output(m.ctx, "ip", "route", "get", "1.1.1.1")
}

func (m *Manager) routeShowMain() ([]byte, error) {
	return m.sys.Output(m.ctx, "ip", "-4", "route", "show", "table", "main", "default")
}

func parseRouteGet(out string) (gateway, iface string, err error) {
	fields := strings.Fields(out)
	for i, f := range fields {
		if f == "via" && i+1 < len(fields) {
			gateway = fields[i+1]
		}
		if f == "dev" && i+1 < len(fields) {
			iface = fields[i+1]
		}
	}
	if iface == "" {
		return "", "", fmt.Errorf("failed to parse route from: %s", out)
	}
	return gateway, iface, nil
}

func (m *Manager) parseMainDefault(out string) (gateway, iface string, err error) {
	var bestMetric uint64
	found := false

	for line := range strings.SplitSeq(out, "\n") {
		fields := strings.Fields(line)
		if len(fields) == 0 || fields[0] != "default" {
			continue
		}

		var lineGateway, lineIface string
		var metric uint64
		for i, f := range fields {
			if i+1 >= len(fields) {
				break
			}
			switch f {
			case "via":
				lineGateway = fields[i+1]
			case "dev":
				lineIface = fields[i+1]
			case "metric":
				if m, perr := strconv.ParseUint(fields[i+1], 10, 32); perr == nil {
					metric = m
				}
			}
		}

		if lineIface == "" || lineIface == m.cfg.Iface {
			continue
		}
		if found && metric >= bestMetric {
			continue
		}
		gateway, iface, bestMetric, found = lineGateway, lineIface, metric, true
	}

	if !found {
		return "", "", fmt.Errorf("no physical default route in table main: %s", out)
	}
	return gateway, iface, nil
}

func (m *Manager) detectNetwork() (gateway, iface string, err error) {
	if out, cmdErr := m.routeShowMain(); cmdErr == nil {
		if gw, ifc, perr := m.parseMainDefault(string(out)); perr == nil {
			return gw, ifc, nil
		}
	}

	out, err := m.routeGet()
	if err != nil {
		return "", "", err
	}
	gateway, iface, err = parseRouteGet(string(out))
	if err != nil {
		return "", "", err
	}
	if iface == m.cfg.Iface {
		return "", "", fmt.Errorf("route lookup landed on %s: the physical uplink is unknown", m.cfg.Iface)
	}
	return gateway, iface, nil
}

func (m *Manager) addRule(args ...string) error {
	for range 8 {
		if err := m.sys.Run(m.ctx, "ip", append([]string{"rule", "del"}, args...)...); err != nil {
			break
		}
	}
	if err := m.sys.Run(m.ctx, "ip", append([]string{"rule", "add"}, args...)...); err != nil {
		logging.Warnf("failed to add ip rule %s: %v", strings.Join(args, " "), err)
		return err
	}
	return nil
}

func (m *Manager) delRule(args ...string) {
	for range 8 {
		if err := m.sys.Run(m.ctx, "ip", append([]string{"rule", "del"}, args...)...); err != nil {
			return
		}
	}
}

func (m *Manager) addBypassRoutes(gateway, iface string) {
	if iface == "" || m.tunnelAsUplink(iface) {
		return
	}
	for _, cidr := range config.BypassCIDRs() {
		args := append([]string{"route", "replace", cidr}, viaArgs(gateway, iface)...)
		args = append(args, "table", tunTable)
		if err := m.sys.Run(m.ctx, "ip", args...); err != nil {
			logging.Warnf("failed to add bypass route %s: %v", cidr, err)
		} else {
			logging.Infof("Bypass route added: %s -> %s (%s) table %s", cidr, gateway, iface, tunTable)
		}
	}
}

func (m *Manager) cleanupLegacyRules() {
	m.delRule("fwmark", fwmark, "table", physTable)
	m.delRule("pref", rulePrefTun, "table", tunTable)
	m.delRule("pref", rulePrefMain, "table", "main", "suppress_prefixlength", "0")
	m.delRule("pref", rulePrefMark, "fwmark", fwmark, "table", physTable)
	m.sys.Try(m.ctx, "ip", "route", "flush", "table", tunTable)
	m.sys.Try(m.ctx, "ip", "route", "flush", "table", physTable)
	m.sys.Try(m.ctx, "ip", "route", "del", "0.0.0.0/1", "dev", m.cfg.Iface)
	m.sys.Try(m.ctx, "ip", "route", "del", "128.0.0.0/1", "dev", m.cfg.Iface)
}

func (m *Manager) cleanupLegacyBypassRoutes(gateway, iface string) {
	if iface == "" {
		return
	}
	for _, cidr := range config.BypassCIDRs() {
		args := append([]string{"route", "del", cidr}, viaArgs(gateway, iface)...)
		m.sys.Try(m.ctx, "ip", args...)
	}
}

func (m *Manager) iptables(args ...string) error {
	return m.sys.Run(m.ctx, "iptables", append([]string{"-w"}, args...)...)
}

func (m *Manager) ip6tables(args ...string) error {
	return m.sys.Run(m.ctx, "ip6tables", append([]string{"-w"}, args...)...)
}

func markRuleArgs(action string) []string {
	return []string{
		"-t", "mangle", action, "OUTPUT",
		"-m", "owner", "--gid-owner", "10001",
		"-j", "MARK", "--set-mark", fwmark,
	}
}

func masqueradeRuleArgs(action, iface string) []string {
	return []string{"-t", "nat", action, "POSTROUTING", "-o", iface, "-j", "MASQUERADE"}
}

func (m *Manager) applyFirewall(iface string) {
	_ = m.iptables(markRuleArgs("-D")...)
	if err := m.iptables(markRuleArgs("-A")...); err != nil {
		logging.Warnf("failed to mark the engine's own packets: %v", err)
	}
	_ = m.iptables(masqueradeRuleArgs("-D", iface)...)
	if err := m.iptables(masqueradeRuleArgs("-A", iface)...); err != nil {
		logging.Warnf("failed to add the masquerade rule for %s: %v", iface, err)
	}
}

func (m *Manager) removeFirewall(iface string) {
	_ = m.iptables(markRuleArgs("-D")...)
	if iface != "" {
		_ = m.iptables(masqueradeRuleArgs("-D", iface)...)
	}
}

func ip6RejectRules(action string) [][]string {
	return [][]string{
		{action, "OUTPUT", "-m", "owner", "--gid-owner", "10001", "-j", "ACCEPT"},
		{action, "OUTPUT", "-d", "2000::/3", "-p", "tcp", "-j", "REJECT", "--reject-with", "tcp-reset"},
		{action, "OUTPUT", "-d", "2000::/3", "-p", "udp", "-j", "REJECT", "--reject-with", "icmp6-port-unreachable"},
	}
}

func (m *Manager) blockIPv6() {
	for _, args := range ip6RejectRules("-D") {
		_ = m.ip6tables(args...)
	}
	for _, args := range ip6RejectRules("-A") {
		if err := m.ip6tables(args...); err != nil {
			logging.Warnf("failed to block IPv6 traffic (%s): %v", strings.Join(args, " "), err)
			return
		}
	}
	logging.Infof("IPv6 traffic to global addresses is rejected while the tunnel is up.")
}

func (m *Manager) unblockIPv6() {
	for _, args := range ip6RejectRules("-D") {
		_ = m.ip6tables(args...)
	}
}

func (m *Manager) applySysctls(iface string) {
	for _, key := range []string{
		"net.ipv4.conf.all.accept_local=1",
		"net.ipv4.conf.all.rp_filter=0",
		"net.ipv4.conf." + iface + ".accept_local=1",
		"net.ipv4.conf." + iface + ".rp_filter=0",
	} {
		m.sys.Try(m.ctx, "sysctl", "-w", key)
	}
}

func (m *Manager) applyUplink(gateway, iface string) {
	if iface == "" || m.tunnelAsUplink(iface) {
		return
	}

	args := append([]string{"route", "replace", "default"}, viaArgs(gateway, iface)...)
	args = append(args, "table", physTable)
	if err := m.sys.Run(m.ctx, "ip", args...); err != nil {
		logging.Warnf("failed to program the physical default route: %v", err)
	}
	_ = m.addRule("pref", rulePrefMark, "fwmark", fwmark, "table", physTable)

	m.applyFirewall(iface)
	m.applySysctls(iface)
	m.syncEdgeRoutes(gateway, iface)
}

func (m *Manager) watchUplink(stop <-chan struct{}) {
	ticker := time.NewTicker(m.pollInterval)
	defer ticker.Stop()

	for {
		select {
		case <-stop:
			return
		case <-ticker.C:
		}

		gateway, iface, err := m.detectNetwork()
		if err != nil {
			continue
		}
		prevGateway, prevIface := m.currentUplink()
		if !m.setUplink(gateway, iface) {
			continue
		}

		logging.Infof("Uplink changed to %s via %s (was %s via %s); reprogramming.",
			iface, gateway, prevIface, prevGateway)

		if prevIface != "" && prevIface != iface {
			m.removeFirewall(prevIface)
		}
		m.applyUplink(gateway, iface)
		if _, err := net.InterfaceByName(m.cfg.Iface); err == nil {
			m.addBypassRoutes(gateway, iface)
		}
		if n := m.onRoutesReset(); n > 0 {
			logging.Infof("Dropped %d session(s) so the tunnel redials over the new uplink.", n)
		}
		m.peer.RefreshAsync()
	}
}

func (m *Manager) awaitTunnelUp(stop <-chan struct{}) bool {
	for {
		if iface, err := m.ifaceByName(m.cfg.Iface); err == nil && iface.Flags&net.FlagUp != 0 {
			return true
		}
		select {
		case <-stop:
			return false
		case <-time.After(m.tunnelPoll):
		}
	}
}

func (m *Manager) waitForTunnel(stop <-chan struct{}) {
	logging.Infof("Waiting for %s...", m.cfg.Iface)
	if !m.awaitTunnelUp(stop) {
		return
	}

	gateway, iface := m.currentUplink()
	logging.Infof("%s detected; activating global routing...", m.cfg.Iface)

	if err := m.sys.Run(m.ctx, "ip", "route", "replace", "default", "dev", m.cfg.Iface, "table", tunTable); err != nil {
		logging.Errorf("failed to point table %s at %s: %v", tunTable, m.cfg.Iface, err)
		return
	}
	m.addBypassRoutes(gateway, iface)

	if err := m.addRule("pref", rulePrefMain, "table", "main", "suppress_prefixlength", "0"); err != nil {
		logging.Errorf("the main table keeps its default route, traffic would bypass the tunnel; not enabling it.")
		return
	}
	if err := m.addRule("pref", rulePrefTun, "table", tunTable); err != nil {
		logging.Errorf("failed to send traffic to table %s; rolling back.", tunTable)
		m.delRule("pref", rulePrefMain, "table", "main", "suppress_prefixlength", "0")
		return
	}

	m.blockIPv6()

	m.sys.Try(m.ctx, "resolvectl", "dns", m.cfg.Iface, m.cfg.Gateway.String())
	m.sys.Try(m.ctx, "resolvectl", "domain", m.cfg.Iface, "~.")
	logging.Infof("Tunnel established.")
}
