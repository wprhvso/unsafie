package fleet

import (
	"math/rand/v2"
	"sync"
	"time"
)

type cellKey struct{ edge, service string }

// Cell is what one server has learned about one service. Kept separate from the
// server's overall reputation on purpose: "clt cannot reach openai" and "clt is
// down" look identical in a single success rate and could not be less alike.
type Cell struct {
	post *Beta
	rtt  *EWMA

	mu       sync.Mutex
	lastOK   time.Time
	lastFail time.Time
	geoUntil time.Time
	touched  time.Time
	opens    uint64
	fails    uint64
	geoHits  uint64
}

func (c *Cell) markOK(now time.Time, latency time.Duration) {
	c.post.Observe(true, 1, now)
	if latency > 0 {
		c.rtt.Add(float64(latency)/float64(time.Millisecond), now)
	}
	c.mu.Lock()
	c.lastOK, c.touched = now, now
	c.opens++
	c.geoUntil = time.Time{}
	c.mu.Unlock()
}

func (c *Cell) markFail(now time.Time, weight float64) {
	c.post.Observe(false, weight, now)
	c.mu.Lock()
	c.lastFail, c.touched = now, now
	c.fails++
	c.mu.Unlock()
}

func (c *Cell) markGeo(now time.Time, ttl time.Duration) {
	c.post.Observe(false, 3, now)
	c.mu.Lock()
	c.lastFail, c.touched = now, now
	c.geoUntil = now.Add(ttl)
	c.geoHits++
	c.fails++
	c.mu.Unlock()
}

func (c *Cell) blocked(now time.Time) bool {
	c.mu.Lock()
	defer c.mu.Unlock()
	return !c.geoUntil.IsZero() && now.Before(c.geoUntil)
}

func (c *Cell) snapshot() (opens, fails, geo uint64, lastOK, lastFail time.Time) {
	c.mu.Lock()
	defer c.mu.Unlock()
	return c.opens, c.fails, c.geoHits, c.lastOK, c.lastFail
}

func (c *Cell) touch(now time.Time) {
	c.mu.Lock()
	c.touched = now
	c.mu.Unlock()
}

func (c *Cell) age(now time.Time) time.Duration {
	c.mu.Lock()
	defer c.mu.Unlock()
	return now.Sub(c.touched)
}

// Table is a bounded memory of those cells. Bounded because a browsing session
// touches thousands of domains and a phone is not a time series database;
// evicted approximately because an exact LRU costs a linked list and a lock on
// every read for a decision that tolerates being slightly wrong.
type Table struct {
	mu    sync.RWMutex
	cells map[cellKey]*Cell
	limit int

	halfLife time.Duration
	rttTau   time.Duration
	rng      *rand.Rand
}

func NewTable(limit int, halfLife, rttTau time.Duration) *Table {
	return &Table{
		cells:    make(map[cellKey]*Cell, limit/2+1),
		limit:    limit,
		halfLife: halfLife,
		rttTau:   rttTau,
		rng:      rand.New(rand.NewPCG(rand.Uint64(), rand.Uint64())),
	}
}

func (t *Table) Peek(edge, svc string) *Cell {
	t.mu.RLock()
	defer t.mu.RUnlock()
	return t.cells[cellKey{edge, svc}]
}

func (t *Table) Cell(edge, svc string) *Cell {
	if c := t.Peek(edge, svc); c != nil {
		return c
	}

	t.mu.Lock()
	defer t.mu.Unlock()

	key := cellKey{edge, svc}
	if c := t.cells[key]; c != nil {
		return c
	}
	if len(t.cells) >= t.limit {
		t.evictLocked()
	}
	c := &Cell{post: NewBeta(t.halfLife), rtt: NewEWMA(t.rttTau), touched: time.Now()}
	t.cells[key] = c
	return c
}

const evictSample = 12

func (t *Table) evictLocked() {
	now := time.Now()
	var (
		victim cellKey
		oldest time.Duration
		seen   int
	)
	for key, c := range t.cells {
		if age := c.age(now); age > oldest {
			victim, oldest = key, age
		}
		seen++
		if seen >= evictSample {
			break
		}
	}
	if seen > 0 {
		delete(t.cells, victim)
	}
}

func (t *Table) Len() int {
	t.mu.RLock()
	defer t.mu.RUnlock()
	return len(t.cells)
}

// Sweep drops cells nothing has asked about for a long time. Decay already
// makes them harmless; this makes them free as well.
func (t *Table) Sweep(now time.Time, idle time.Duration) int {
	t.mu.Lock()
	defer t.mu.Unlock()

	n := 0
	for key, c := range t.cells {
		if c.age(now) > idle {
			delete(t.cells, key)
			n++
		}
	}
	return n
}

func (t *Table) Each(fn func(edge, svc string, c *Cell)) {
	t.mu.RLock()
	defer t.mu.RUnlock()
	for key, c := range t.cells {
		fn(key.edge, key.service, c)
	}
}
