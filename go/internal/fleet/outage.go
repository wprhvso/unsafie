package fleet

import (
	"sync"
	"time"

	"unsafie/internal/logging"
)

// outage tells "the servers are down" apart from "you are on a train".
//
// Without it the first thing a client does when the Wi-Fi drops is convict all
// three servers of being unreachable, and the first thing it does when the
// Wi-Fi comes back is spend a minute rediscovering that they were fine. The
// rule is simple and hard to argue with: if every server failed inside the same
// short window and none of them succeeded, the one thing they have in common is
// the network in front of them.
type outage struct {
	mu     sync.Mutex
	window time.Duration

	failed   map[string]time.Time
	lastOK   time.Time
	active   bool
	since    time.Time
	snap     map[string][2]float64
	episodes uint64
}

func newOutage(window time.Duration) *outage {
	return &outage{window: window, failed: map[string]time.Time{}}
}

func (f *Fleet) snapshot() map[string][2]float64 {
	out := make(map[string][2]float64, len(f.nodes))
	for _, n := range f.nodes {
		a, b := n.post.Snapshot()
		out[n.name()] = [2]float64{a, b}
	}
	return out
}

func (f *Fleet) restore(snap map[string][2]float64) {
	for _, n := range f.nodes {
		if v, ok := snap[n.name()]; ok {
			n.post.Restore(v[0], v[1])
		}
	}
}

// noteOutage records one server level failure and answers whether the fleet is
// currently being punished for something that is not its fault.
func (f *Fleet) noteOutage(name string, now time.Time) bool {
	o := f.out

	o.mu.Lock()
	defer o.mu.Unlock()

	o.failed[name] = now
	for k, at := range o.failed {
		if now.Sub(at) > o.window {
			delete(o.failed, k)
		}
	}

	if o.active {
		return true
	}
	if len(o.failed) < len(f.nodes) {
		return false
	}
	if !o.lastOK.IsZero() && now.Sub(o.lastOK) < o.window {
		return false
	}

	o.active = true
	o.since = now
	o.episodes++
	o.snap = f.snapshot()
	f.local.Add(1)
	logging.Infof("Fleet: all %d servers failed within %s and none answered; blaming the local network, not them.",
		len(f.nodes), o.window)
	return true
}

func (f *Fleet) clearOutage(now time.Time) {
	o := f.out

	o.mu.Lock()
	o.lastOK = now
	clear(o.failed)
	active, snap, since := o.active, o.snap, o.since
	o.active, o.snap = false, nil
	o.mu.Unlock()

	if !active {
		return
	}
	f.restore(snap)
	logging.Infof("Fleet: the local network came back after %s; the servers keep the reputation they had before it went.",
		now.Sub(since).Round(time.Second))
}

func (f *Fleet) LocalOutage() bool {
	f.out.mu.Lock()
	defer f.out.mu.Unlock()
	return f.out.active
}

func (f *Fleet) OutageEpisodes() uint64 {
	f.out.mu.Lock()
	defer f.out.mu.Unlock()
	return f.out.episodes
}
