package backoff

import (
	"math/rand/v2"
	"sync"
	"time"
)

// Decorrelated jitter: the next delay is drawn from [base, previous*3]. It
// spreads a fleet of clients that all lost the same server at the same second
// far better than doubling does, and it recovers faster than full jitter when
// the outage was short.
type Jitter struct {
	Base time.Duration
	Max  time.Duration

	mu   sync.Mutex
	last time.Duration
	rng  *rand.Rand
}

func New(base, maximum time.Duration) *Jitter {
	return &Jitter{
		Base: base,
		Max:  maximum,
		rng:  rand.New(rand.NewPCG(rand.Uint64(), rand.Uint64())),
	}
}

func (j *Jitter) Next() time.Duration {
	j.mu.Lock()
	defer j.mu.Unlock()

	if j.last == 0 {
		j.last = j.Base
		return j.Base
	}
	span := int64(j.last)*3 - int64(j.Base)
	if span < 1 {
		span = 1
	}
	next := time.Duration(int64(j.Base) + j.rng.Int64N(span))
	if next > j.Max {
		next = j.Max
	}
	j.last = next
	return next
}

func (j *Jitter) Reset() {
	j.mu.Lock()
	j.last = 0
	j.mu.Unlock()
}

func (j *Jitter) Peek() time.Duration {
	j.mu.Lock()
	defer j.mu.Unlock()
	return j.last
}

// Spread returns d scattered by up to ±fraction of itself. Rotating long lived
// connections on an exact schedule is a fingerprint of its own.
func Spread(d time.Duration, fraction float64) time.Duration {
	if d <= 0 || fraction <= 0 {
		return d
	}
	span := float64(d) * fraction
	return d + time.Duration((rand.Float64()*2-1)*span)
}
