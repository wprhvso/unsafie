package fleet

import (
	"context"
	"fmt"
	"strings"
	"sync"
	"time"

	"unsafie/internal/edge"
	"unsafie/internal/logging"
	"unsafie/internal/usp"
)

const (
	probeTimeout = 6 * time.Second
	sweepEvery   = 5 * time.Minute
	sweepIdle    = 2 * time.Hour
	reportEvery  = 2 * time.Minute
)

// Run keeps opinions fresh. A picker that only learns from traffic learns
// nothing about the server it stopped using, which is how a fleet quietly
// collapses onto one server and stays there after the other two recover.
func (f *Fleet) Run(ctx context.Context) {
	f.warm(ctx)

	probe := time.NewTicker(f.opts.ProbeInterval)
	defer probe.Stop()
	sweep := time.NewTicker(sweepEvery)
	defer sweep.Stop()
	report := time.NewTicker(reportEvery)
	defer report.Stop()

	for {
		select {
		case <-ctx.Done():
			return
		case <-probe.C:
			f.probeAll(ctx)
		case <-sweep.C:
			if n := f.table.Sweep(time.Now(), sweepIdle); n > 0 {
				logging.Infof("Fleet: forgot %d service(s) nothing has asked about in %s", n, sweepIdle)
			}
			f.services.Set(int64(f.table.Len()))
		case <-report.C:
			logging.Infof("Fleet: %s", f.Status())
		}
	}
}

func (f *Fleet) warm(ctx context.Context) {
	var wg sync.WaitGroup
	for _, n := range f.nodes {
		wg.Add(1)
		go func() {
			defer wg.Done()
			warmCtx, cancel := context.WithTimeout(ctx, 2*probeTimeout)
			defer cancel()
			if err := n.e.Warm(warmCtx); err != nil {
				logging.Infof("Fleet: %s did not warm up: %v", n.name(), err)
			}
		}()
	}
	wg.Wait()
}

func (f *Fleet) probeAll(ctx context.Context) {
	var wg sync.WaitGroup
	for _, n := range f.nodes {
		wg.Add(1)
		go func() {
			defer wg.Done()
			f.probe(ctx, n)
		}()
	}
	wg.Wait()
}

func (f *Fleet) probe(ctx context.Context, n *node) {
	now := time.Now()
	if left := n.breaker.RetryIn(now); left > 0 {
		n.phi.SetFloat(n.accrual.Phi(now))
		return
	}

	probeCtx, cancel := context.WithTimeout(ctx, probeTimeout)
	defer cancel()

	started := time.Now()
	rtt, err := n.e.Ping(probeCtx)
	if err != nil {
		fault, reason := edge.Classify(err)
		if fault == usp.FaultNone {
			return
		}
		f.Report(edge.Result{Edge: n.name(), Fault: fault, Reason: reason, Latency: time.Since(started), Err: err})
		return
	}

	now = time.Now()
	n.accrual.Heartbeat(now)
	n.rtt.Add(float64(rtt)/float64(time.Millisecond), now)
	n.post.Observe(true, 0.25, now)
	n.breaker.Success(now)
	n.lastOK.Store(now.UnixNano())
	n.theta.SetFloat(n.post.Mean(now))
	n.phi.SetFloat(n.accrual.Phi(now))
	n.state.Set(int64(n.breaker.State()))
	f.clearOutage(now)
}

type EdgeStatus struct {
	Name     string
	Host     string
	Region   string
	Country  string
	Protocol string
	Breaker  string
	Belief   float64
	Phi      float64
	RTT      time.Duration
	Streams  int64
	Live     bool
}

type Overview struct {
	Edges  []EdgeStatus
	Local  bool
	Cells  int
	Sticky int
}

func (f *Fleet) Snapshot() Overview {
	now := time.Now()
	out := Overview{Local: f.LocalOutage(), Cells: f.table.Len()}

	f.stickyMu.Lock()
	out.Sticky = len(f.sticky)
	f.stickyMu.Unlock()

	for _, n := range f.nodes {
		out.Edges = append(out.Edges, EdgeStatus{
			Name:     n.name(),
			Host:     n.e.Host(),
			Region:   n.e.Region(),
			Country:  n.e.Country(),
			Protocol: n.e.Protocol(),
			Breaker:  n.breaker.State().String(),
			Belief:   n.post.Mean(now),
			Phi:      n.accrual.Phi(now),
			RTT:      time.Duration(n.rtt.Value() * float64(time.Millisecond)),
			Streams:  n.e.Streams(),
			Live:     n.e.Live(),
		})
	}
	return out
}

func (f *Fleet) Status() string {
	s := f.Snapshot()

	var b strings.Builder
	for i, e := range s.Edges {
		if i > 0 {
			b.WriteString(" | ")
		}
		fmt.Fprintf(&b, "%s %s %s p=%.2f phi=%.1f rtt=%s streams=%d",
			e.Name, e.Protocol, e.Breaker, e.Belief, e.Phi,
			e.RTT.Round(time.Millisecond), e.Streams)
		if e.Country != "" {
			fmt.Fprintf(&b, " %s", e.Country)
		}
	}
	if s.Local {
		b.WriteString(" | local outage")
	}
	fmt.Fprintf(&b, " | services=%d sticky=%d", s.Cells, s.Sticky)
	return b.String()
}
