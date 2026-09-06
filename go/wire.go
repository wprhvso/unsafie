package main

import (
	"context"
	"crypto/rand"
	"encoding/binary"
	"net"
	"net/http"
	"strings"
	"sync/atomic"
	"time"

	"unsafie/internal/chrome"
	"unsafie/internal/edge"
	"unsafie/internal/fleet"
	"unsafie/internal/logging"
	"unsafie/internal/metrics"
	"unsafie/internal/resolve"
	"unsafie/internal/usp"
)

var bootstrapResolver = resolve.BootstrapResolver{Dial: dialDirect}

var edgeGroup = resolve.NewGroup(edgeHosts(), buildPort,
	resolve.WithResolver(bootstrapResolver),
	resolve.WithOnChange(onEdgeChange),
)

var edgeDialer = &resolve.Dialer{Group: edgeGroup, Base: dialDirect}

func edgeHosts() []string {
	var out []string
	for _, h := range strings.Split(buildEdges, ",") {
		if h = strings.TrimSpace(h); h != "" {
			out = append(out, h)
		}
	}
	return out
}

func shortName(host string) string {
	label, _, _ := strings.Cut(host, ".")
	if label == "" {
		return host
	}
	return label
}

func dialDirect(ctx context.Context, network, address string) (net.Conn, error) {
	if plat == nil {
		return nil, resolve.ErrNoPlatform
	}
	return plat.DialDirect(ctx, network, address)
}

var edgeChangeHook func()

func setEdgeChangeHook(f func()) { edgeChangeHook = f }

func onEdgeChange(replaced bool) {
	if replaced {
		if n := resetEdgeSessions(); n > 0 {
			logging.Infof("Edge addresses changed; dropped %d session(s).", n)
		}
	}
	if f := edgeChangeHook; f != nil {
		go f()
	}
}

func resetEdgeSessions() int {
	e := current.Load()
	if e == nil {
		return 0
	}
	return e.reset()
}

// stateDir is where sessions are left for the next run. Android hands it over
// through JNI because an app has no business writing anywhere else; everyone
// else gets the build-time default.
var stateOverride atomic.Pointer[string]

func SetStateDir(dir string) { stateOverride.Store(&dir) }

func stateDir() string {
	if dir := stateOverride.Load(); dir != nil {
		return *dir
	}
	return buildStateDir
}

func padder() usp.Padder {
	var seed [8]byte
	_, _ = rand.Read(seed[:])
	return usp.NewJitterPad(binary.BigEndian.Uint64(seed[:]), 512, 96)
}

func newWire(host, port string) edge.Wire {
	return chrome.NewWire(chrome.Options{
		Profile:    chrome.Chrome131,
		Host:       host,
		Port:       port,
		Dial:       edgeDialer.DialContext,
		ListenUDP:  listenUDP,
		ResolveUDP: resolveUDP,
		Insecure:   buildInsecureTLS == "1",
		EnableH3:   buildDisableH3 != "1",
		AllowRetry: true,
	})
}

func listenUDP(ctx context.Context) (net.PacketConn, error) {
	if plat == nil {
		return nil, resolve.ErrNoPlatform
	}
	return plat.ListenPacket(ctx)
}

func resolveUDP(_ context.Context, host, port string) (*net.UDPAddr, error) {
	ep := edgeGroup.Endpoint(host)
	if ep == nil {
		return nil, chrome.ErrNoAddress
	}
	targets := ep.DialTargets()
	if len(targets) == 0 {
		ep.RefreshAsync()
		return nil, chrome.ErrNoAddress
	}
	_ = port
	return net.UDPAddrFromAddrPort(targets[0]), nil
}

func buildFleet() *fleet.Fleet {
	var live *fleet.Fleet
	report := func(r edge.Result) {
		if live != nil {
			live.Report(r)
		}
	}

	pad := padder()
	store := edge.NewStore(stateDir(), 90*time.Second)
	edges := make([]*edge.Edge, 0, len(edgeGroup.Endpoints()))
	for _, ep := range edgeGroup.Endpoints() {
		edges = append(edges, edge.New(edge.Config{
			Name:     shortName(ep.Host()),
			Host:     ep.Host(),
			Port:     ep.Port(),
			Bearer:   buildBearer,
			Label:    "unsafie/" + buildVersion,
			Slots:    buildSlots,
			Parallel: 3,
			Replay:   4 << 20,
			Padder:   pad,
			State:    store,
			NewWire:  newWire,
			Report:   report,
		}))
	}

	live = fleet.New(fleet.Options{
		Edges:         edges,
		Registry:      metrics.Default,
		StickyTTL:     5 * time.Minute,
		GeoTTL:        30 * time.Minute,
		HalfLife:      4 * time.Minute,
		ProbeInterval: 15 * time.Second,
	})
	return live
}

func serveStatus(ctx context.Context, f *fleet.Fleet) {
	if buildStatusAddr == "" {
		return
	}

	mux := http.NewServeMux()
	mux.HandleFunc("/metrics", func(w http.ResponseWriter, _ *http.Request) {
		w.Header().Set("Content-Type", "text/plain; version=0.0.4; charset=utf-8")
		_, _ = metrics.Default.WriteTo(w)
	})
	mux.HandleFunc("/status", func(w http.ResponseWriter, _ *http.Request) {
		w.Header().Set("Content-Type", "text/plain; charset=utf-8")
		_, _ = w.Write([]byte(f.Status() + "\n"))
	})
	mux.HandleFunc("/fingerprint", func(w http.ResponseWriter, _ *http.Request) {
		_, _ = w.Write([]byte(chrome.Chrome131.Fingerprint() + "\n"))
	})

	srv := &http.Server{
		Addr:              buildStatusAddr,
		Handler:           mux,
		ReadHeaderTimeout: 5 * time.Second,
	}
	go func() {
		<-ctx.Done()
		_ = srv.Close()
	}()
	if err := srv.ListenAndServe(); err != nil && ctx.Err() == nil {
		logging.Infof("Status endpoint on %s stopped: %v", buildStatusAddr, err)
	}
}
