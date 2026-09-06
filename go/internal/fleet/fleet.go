package fleet

import (
	"context"
	"errors"
	"math"
	"math/rand/v2"
	"net"
	"slices"
	"sync"
	"sync/atomic"
	"time"

	"unsafie/internal/edge"
	"unsafie/internal/logging"
	"unsafie/internal/metrics"
	"unsafie/internal/netx"
	"unsafie/internal/service"
	"unsafie/internal/usp"
)

var ErrNoEdge = errors.New("fleet: no server is usable")

const (
	shrinkAt     = 6.0
	geoPenalty   = 0.02
	coolPenalty  = 0.05
	phiSuspect   = 5.0
	stickyBonus  = 1.35
	regionBonus  = 1.2
	loadPivot    = 48.0
	minCostMS    = 4.0
	firstByteTTL = 20 * time.Second
)

type Options struct {
	Edges    []*edge.Edge
	Registry *metrics.Registry

	StickyTTL     time.Duration
	GeoTTL        time.Duration
	HalfLife      time.Duration
	RTTTau        time.Duration
	MaxServices   int
	ProbeInterval time.Duration
	HedgeQuantile float64
	MinHedge      time.Duration
	MaxHedge      time.Duration
	OutageWindow  time.Duration
}

func (o *Options) fill() {
	if o.StickyTTL == 0 {
		o.StickyTTL = 5 * time.Minute
	}
	if o.GeoTTL == 0 {
		o.GeoTTL = 30 * time.Minute
	}
	if o.HalfLife == 0 {
		o.HalfLife = 4 * time.Minute
	}
	if o.RTTTau == 0 {
		o.RTTTau = 30 * time.Second
	}
	if o.MaxServices == 0 {
		o.MaxServices = 8192
	}
	if o.ProbeInterval == 0 {
		o.ProbeInterval = 15 * time.Second
	}
	if o.HedgeQuantile == 0 {
		o.HedgeQuantile = 0.90
	}
	if o.MinHedge == 0 {
		o.MinHedge = 120 * time.Millisecond
	}
	if o.MaxHedge == 0 {
		o.MaxHedge = 1200 * time.Millisecond
	}
	if o.OutageWindow == 0 {
		o.OutageWindow = 12 * time.Second
	}
	if o.Registry == nil {
		o.Registry = metrics.Default
	}
}

type node struct {
	e       *edge.Edge
	post    *Beta
	rtt     *EWMA
	openLat *metrics.Histogram
	breaker *Breaker
	accrual *Accrual

	lastOK   atomic.Int64
	lastFail atomic.Int64

	picks  *metrics.Counter
	wins   *metrics.Counter
	losses *metrics.Counter
	hedges *metrics.Counter
	faults map[usp.Fault]*metrics.Counter
	state  *metrics.Gauge
	theta  *metrics.Gauge
	phi    *metrics.Gauge
}

func (n *node) name() string { return n.e.Name() }

type stickyEntry struct {
	node    *node
	expires time.Time
}

type Fleet struct {
	opts  Options
	nodes []*node
	index map[string]*node
	table *Table
	reg   *metrics.Registry

	rngMu sync.Mutex
	rng   *rand.Rand

	stickyMu sync.Mutex
	sticky   map[string]stickyEntry

	out *outage

	dials    *metrics.Counter
	failures *metrics.Counter
	races    *metrics.Counter
	blind    *metrics.Counter
	local    *metrics.Counter
	services *metrics.Gauge
}

func New(opts Options) *Fleet {
	opts.fill()

	f := &Fleet{
		opts:   opts,
		index:  make(map[string]*node, len(opts.Edges)),
		table:  NewTable(opts.MaxServices, opts.HalfLife, opts.RTTTau),
		reg:    opts.Registry,
		rng:    rand.New(rand.NewPCG(rand.Uint64(), rand.Uint64())),
		sticky: make(map[string]stickyEntry),
		out:    newOutage(opts.OutageWindow),
	}

	for _, e := range opts.Edges {
		l := metrics.Labels{"edge": e.Name()}
		n := &node{
			e:       e,
			post:    NewBeta(opts.HalfLife),
			rtt:     NewEWMA(opts.RTTTau),
			openLat: f.reg.Histogram("unsafie_edge_open_latency_ms", "time from dial to a usable stream", l),
			breaker: NewBreaker(4, 2*time.Second, 2*time.Minute),
			accrual: NewAccrual(32),
			picks:   f.reg.Counter("unsafie_edge_picks_total", "connections handed to this server", l),
			wins:    f.reg.Counter("unsafie_edge_wins_total", "connections this server carried", l),
			losses:  f.reg.Counter("unsafie_edge_losses_total", "connections this server failed", l),
			hedges:  f.reg.Counter("unsafie_edge_hedges_total", "hedged attempts started on this server", l),
			state:   f.reg.Gauge("unsafie_edge_breaker_state", "0 closed, 1 open, 2 half-open", l),
			theta:   f.reg.Gauge("unsafie_edge_success_belief", "posterior mean of the success probability", l),
			phi:     f.reg.Gauge("unsafie_edge_phi", "phi accrual suspicion level", l),
			faults:  map[usp.Fault]*metrics.Counter{},
		}
		for _, fault := range []usp.Fault{usp.FaultEdge, usp.FaultExit, usp.FaultService, usp.FaultGeo, usp.FaultLocal} {
			n.faults[fault] = f.reg.Counter("unsafie_edge_faults_total", "failures by whose fault they look like",
				metrics.Labels{"edge": e.Name(), "fault": fault.String()})
		}
		f.nodes = append(f.nodes, n)
		f.index[e.Name()] = n
	}

	f.dials = f.reg.Counter("unsafie_dials_total", "tunnelled connections attempted", nil)
	f.failures = f.reg.Counter("unsafie_dial_failures_total", "tunnelled connections that found no server", nil)
	f.races = f.reg.Counter("unsafie_hedged_dials_total", "dials that were raced across servers", nil)
	f.blind = f.reg.Counter("unsafie_optimistic_dials_total", "dials sent without waiting for the exit", nil)
	f.local = f.reg.Counter("unsafie_local_outages_total", "episodes blamed on the client's own network", nil)
	f.services = f.reg.Gauge("unsafie_known_services", "services the picker remembers", nil)

	return f
}

func (f *Fleet) Edges() []*edge.Edge {
	out := make([]*edge.Edge, 0, len(f.nodes))
	for _, n := range f.nodes {
		out = append(out, n.e)
	}
	return out
}

func (f *Fleet) Close() {
	for _, n := range f.nodes {
		n.e.Close()
	}
}

func (f *Fleet) Reset() int {
	n := 0
	for _, node := range f.nodes {
		n += node.e.Reset()
	}
	return n
}

// Suspend leaves the exits holding their sessions so the next run can pick them
// up instead of paying for new ones.
func (f *Fleet) Suspend() {
	for _, n := range f.nodes {
		n.e.Suspend()
	}
}

func (f *Fleet) sample(fn func(*rand.Rand) float64) float64 {
	f.rngMu.Lock()
	defer f.rngMu.Unlock()
	return fn(f.rng)
}

type candidate struct {
	node    *node
	score   float64
	theta   float64
	cost    float64
	blocked bool
	cooling bool
}

// rank is the whole opinion of the client in one function.
//
// Thompson sampling over a decayed Beta posterior instead of a success rate:
// it explores a server that has been failing just often enough to notice when
// it comes back, and stops as soon as the evidence says it has not. The per
// service posterior is shrunk towards the server's overall reputation in
// proportion to how much evidence the cell actually holds, so the first
// connection to a new domain is not decided by a coin flip.
//
// The score is a belief divided by a cost, which is what "best" has to mean
// when one server is twice as likely to work and three times as far away.
func (f *Fleet) rank(svc string, now time.Time) []candidate {
	sticky := f.stickyNode(svc, now)
	out := make([]candidate, 0, len(f.nodes))

	for _, n := range f.nodes {
		cell := f.table.Peek(n.name(), svc)

		theta := f.sample(func(r *rand.Rand) float64 { return n.post.Sample(r, now) })
		if cell != nil {
			w := math.Min(1, cell.post.Weight(now)/shrinkAt)
			local := f.sample(func(r *rand.Rand) float64 { return cell.post.Sample(r, now) })
			theta = w*local + (1-w)*theta
		}

		cost := math.Max(n.expectedCost(cell), minCostMS)
		score := theta / cost

		c := candidate{node: n, theta: theta, cost: cost}
		if cell != nil && cell.blocked(now) {
			score *= geoPenalty
			c.blocked = true
		}
		if left := n.breaker.RetryIn(now); left > 0 {
			score *= coolPenalty
			c.cooling = true
		}
		if phi := n.accrual.Phi(now); phi > phiSuspect {
			score *= math.Exp(-(phi - phiSuspect))
			n.phi.SetFloat(phi)
		}
		score *= loadPivot / (loadPivot + float64(n.e.Streams()))
		if sticky == n {
			score *= stickyBonus
		}
		if f.regionPreferred(svc, n, now) {
			score *= regionBonus
		}

		c.score = score
		out = append(out, c)
	}

	slices.SortFunc(out, func(a, b candidate) int {
		switch {
		case a.score > b.score:
			return -1
		case a.score < b.score:
			return 1
		default:
			return 0
		}
	})
	return out
}

// regionPreferred answers the "this only works from the United States" case:
// a service that has succeeded from one country and been geo blocked from
// another is not a coin flip any more, and the country is what generalises,
// not the individual server.
func (f *Fleet) regionPreferred(svc string, n *node, now time.Time) bool {
	country := n.e.Country()
	if country == "" {
		return false
	}
	good, bad := 0, 0
	for _, other := range f.nodes {
		if other.e.Country() != country {
			continue
		}
		cell := f.table.Peek(other.name(), svc)
		if cell == nil {
			continue
		}
		opens, _, geo, _, _ := cell.snapshot()
		if geo > 0 {
			bad++
		} else if opens > 0 {
			good++
		}
	}
	return good > 0 && bad == 0
}

func (n *node) expectedCost(cell *Cell) float64 {
	cost := n.rtt.Value()
	if !n.rtt.Known() {
		cost = float64(n.e.RTT()) / float64(time.Millisecond)
	}
	if cost <= 0 {
		cost = 60
	}
	if cell != nil && cell.rtt.Known() {
		cost = 0.5*cost + 0.5*cell.rtt.Value()
	}
	return cost
}

func (f *Fleet) stickyNode(svc string, now time.Time) *node {
	f.stickyMu.Lock()
	defer f.stickyMu.Unlock()
	entry, ok := f.sticky[svc]
	if !ok || now.After(entry.expires) {
		return nil
	}
	return entry.node
}

func (f *Fleet) remember(svc string, n *node, now time.Time) {
	f.stickyMu.Lock()
	f.sticky[svc] = stickyEntry{node: n, expires: now.Add(f.opts.StickyTTL)}
	if len(f.sticky) > f.opts.MaxServices {
		for k, v := range f.sticky {
			if now.After(v.expires) {
				delete(f.sticky, k)
			}
		}
	}
	f.stickyMu.Unlock()
}

func (f *Fleet) forget(svc string, n *node) {
	f.stickyMu.Lock()
	if entry, ok := f.sticky[svc]; ok && entry.node == n {
		delete(f.sticky, svc)
	}
	f.stickyMu.Unlock()
}

func (f *Fleet) Dial(ctx context.Context, network, address string) (net.Conn, error) {
	host, _ := netx.SplitTarget(address)
	svc := service.Key(host)
	now := time.Now()

	f.dials.Add(1)
	order := f.rank(svc, now)

	if len(order) > 0 && f.confident(order, svc, now) {
		lead := order[0].node
		if lead.breaker.Allow(now) {
			lead.picks.Add(1)
			f.blind.Add(1)
			started := time.Now()
			conn, err := lead.e.Dial(ctx, network, address)
			if err == nil {
				f.remember(svc, lead, started)
				return f.witness(conn, lead, svc, started), nil
			}
			f.observe(lead, svc, err, time.Since(started))
			order = order[1:]
		}
	}

	conn, err := f.race(ctx, network, address, svc, order)
	if err != nil {
		f.failures.Add(1)
	}
	return conn, err
}

// confident decides whether the leader may be used without a confirmation round
// trip. Optimistic opens are worth a whole RTT on every connection, and the
// only thing they cost is a wasted attempt when the leader turns out to be
// wrong — which is exactly what a healthy cell with a clear lead says will not
// happen.
func (f *Fleet) confident(order []candidate, svc string, now time.Time) bool {
	lead := order[0]
	if lead.blocked || lead.cooling {
		return false
	}
	cell := f.table.Peek(lead.node.name(), svc)
	if cell == nil || cell.post.Weight(now) < shrinkAt {
		return false
	}
	if opens, fails, _, lastOK, _ := cell.snapshot(); opens == 0 || fails > opens || now.Sub(lastOK) > f.opts.StickyTTL {
		return false
	}
	if len(order) == 1 {
		return true
	}
	return lead.score > order[1].score*1.5
}

// race stages attempts instead of running them one after another. A server that
// is being blackholed does not answer at all, and a sequential walk pays its
// whole timeout before trying the neighbour that was fine. The delay before the
// second attempt is the leader's own p90, so a healthy fleet almost never pays
// for the second one.
func (f *Fleet) race(ctx context.Context, network, address, svc string, order []candidate) (net.Conn, error) {
	usable := make([]candidate, 0, len(order))
	now := time.Now()
	for _, c := range order {
		if c.node.breaker.Allow(now) {
			usable = append(usable, c)
		}
	}
	if len(usable) == 0 && len(order) > 0 {
		order[0].node.breaker.Force()
		usable = order[:1]
	}
	if len(usable) == 0 {
		return nil, ErrNoEdge
	}

	dialCtx, cancel := context.WithCancel(ctx)

	type attempt struct {
		cand  candidate
		conn  net.Conn
		err   error
		spent time.Duration
	}
	results := make(chan attempt, len(usable))

	started, pending := 0, 0
	launch := func() {
		c := usable[started]
		started++
		pending++
		c.node.picks.Add(1)
		if started > 1 {
			c.node.hedges.Add(1)
		}
		go func() {
			at := time.Now()
			conn, err := c.node.e.DialStrict(dialCtx, network, address)
			results <- attempt{cand: c, conn: conn, err: err, spent: time.Since(at)}
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

	if len(usable) > 1 {
		f.races.Add(1)
	}

	hedge := time.NewTimer(f.hedgeDelay(usable[0].node))
	defer hedge.Stop()
	launch()

	var last error
	for pending > 0 || started < len(usable) {
		var tick <-chan time.Time
		if started < len(usable) {
			tick = hedge.C
		}

		select {
		case <-tick:
			launch()
			hedge.Reset(f.hedgeDelay(usable[min(started, len(usable)-1)].node))

		case a := <-results:
			pending--
			if a.err == nil {
				f.win(a.cand.node, svc, a.spent)
				return f.witness(a.conn, a.cand.node, svc, time.Now()), nil
			}
			last = a.err
			f.observe(a.cand.node, svc, a.err, a.spent)
			if ctx.Err() != nil {
				return nil, ctx.Err()
			}
			if started < len(usable) {
				launch()
				if !hedge.Stop() {
					select {
					case <-hedge.C:
					default:
					}
				}
				hedge.Reset(f.hedgeDelay(usable[min(started, len(usable)-1)].node))
			}

		case <-ctx.Done():
			return nil, ctx.Err()
		}
	}

	if last == nil {
		last = ErrNoEdge
	}
	return nil, last
}

func (f *Fleet) hedgeDelay(n *node) time.Duration {
	q := n.openLat.Quantile(f.opts.HedgeQuantile)
	d := time.Duration(q) * time.Millisecond
	if n.openLat.Count() < 8 {
		d = f.opts.MinHedge
	}
	return max(f.opts.MinHedge, min(d, f.opts.MaxHedge))
}

func (f *Fleet) win(n *node, svc string, spent time.Duration) {
	now := time.Now()
	n.wins.Add(1)
	n.openLat.ObserveDuration(spent)
	n.post.Observe(true, 1, now)
	n.rtt.Add(float64(spent)/float64(time.Millisecond), now)
	n.breaker.Success(now)
	n.accrual.Heartbeat(now)
	n.lastOK.Store(now.UnixNano())
	n.theta.SetFloat(n.post.Mean(now))
	f.table.Cell(n.name(), svc).markOK(now, spent)
	f.remember(svc, n, now)
	f.clearOutage(now)
	f.services.Set(int64(f.table.Len()))
}

func (f *Fleet) observe(n *node, svc string, err error, spent time.Duration) {
	fault, reason := edge.Classify(err)
	f.Report(edge.Result{
		Edge:    n.name(),
		Service: svc,
		Fault:   fault,
		Reason:  reason,
		Latency: spent,
		Err:     err,
	})
}

// Report is the single place a verdict turns into a change of opinion. Faults
// arrive here from three directions — a dial that failed, a stream the exit
// reset later, a probe that went unanswered — and they all have to be weighed
// the same way or the model quietly develops two personalities.
func (f *Fleet) Report(r edge.Result) {
	n := f.index[r.Edge]
	if n == nil {
		return
	}
	now := time.Now()

	if c, ok := n.faults[r.Fault]; ok && r.Fault != usp.FaultNone {
		c.Add(1)
	}

	switch r.Fault {
	case usp.FaultNone:
		n.accrual.Heartbeat(now)
		n.breaker.Success(now)
		n.post.Observe(true, 0.5, now)
		n.lastOK.Store(now.UnixNano())
		f.clearOutage(now)
		if r.Service != "" {
			f.table.Cell(n.name(), r.Service).markOK(now, r.Latency)
		}

	case usp.FaultEdge, usp.FaultLocal:
		n.losses.Add(1)
		n.lastFail.Store(now.UnixNano())
		n.breaker.Failure(now)
		if !f.noteOutage(n.name(), now) {
			n.post.Observe(false, 1, now)
		}
		if r.Service != "" {
			f.forget(r.Service, n)
		}

	case usp.FaultExit:
		n.losses.Add(1)
		n.post.Observe(false, 0.25, now)
		if r.Service != "" {
			f.table.Cell(n.name(), r.Service).markFail(now, 1)
			f.forget(r.Service, n)
		}

	case usp.FaultGeo:
		if r.Service != "" {
			f.table.Cell(n.name(), r.Service).markGeo(now, f.opts.GeoTTL)
			f.forget(r.Service, n)
			logging.Infof("Fleet: %s looks geo-blocked from %s (%s); avoiding it for %s",
				r.Service, n.name(), n.e.Country(), f.opts.GeoTTL)
		}

	case usp.FaultService:
		if r.Service != "" {
			f.table.Cell(n.name(), r.Service).touch(now)
		}
	}

	n.theta.SetFloat(n.post.Mean(now))
	n.state.Set(int64(n.breaker.State()))
	f.services.Set(int64(f.table.Len()))
}

// witness watches the first byte back from the destination. A stream that opens
// and then says nothing is the shape a silent block takes, and it is the only
// failure the exit cannot report because from where it stands nothing is wrong.
func (f *Fleet) witness(conn net.Conn, n *node, svc string, at time.Time) net.Conn {
	w := &witnessConn{Conn: conn, fleet: f, node: n, svc: svc, at: at}
	time.AfterFunc(firstByteTTL, func() {
		if w.seen.Load() || w.closed.Load() {
			return
		}
		f.Report(edge.Result{
			Edge:    n.name(),
			Service: svc,
			Fault:   usp.FaultExit,
			Reason:  usp.ReasonHandshakeStall,
			Latency: firstByteTTL,
		})
	})
	return w
}

type witnessConn struct {
	net.Conn
	fleet  *Fleet
	node   *node
	svc    string
	at     time.Time
	seen   atomic.Bool
	closed atomic.Bool
}

func (c *witnessConn) Read(p []byte) (int, error) {
	n, err := c.Conn.Read(p)
	if n > 0 && !c.seen.Swap(true) {
		c.node.e.Succeeded(c.svc, time.Since(c.at))
	}
	return n, err
}

func (c *witnessConn) Close() error {
	c.closed.Store(true)
	return c.Conn.Close()
}

func (c *witnessConn) CloseWrite() error {
	if cw, ok := c.Conn.(interface{ CloseWrite() error }); ok {
		return cw.CloseWrite()
	}
	return errors.ErrUnsupported
}

func (c *witnessConn) SetReadLinger(d time.Duration) {
	if l, ok := c.Conn.(interface{ SetReadLinger(time.Duration) }); ok {
		l.SetReadLinger(d)
	}
}
