package fleet

import (
	"math"
	"math/rand/v2"
	"sync"
	"time"
)

// Beta is a Bernoulli posterior that forgets. Counting successes and failures
// forever means a server that was broken for an hour last week outvotes the
// hour it has been perfect since; halving the evidence on a schedule keeps the
// answer about the present without throwing the past away in one step.
type Beta struct {
	mu       sync.Mutex
	alpha    float64
	beta     float64
	halfLife time.Duration
	last     time.Time
}

const (
	priorAlpha = 1.0
	priorBeta  = 1.0
)

func NewBeta(halfLife time.Duration) *Beta {
	return &Beta{alpha: priorAlpha, beta: priorBeta, halfLife: halfLife, last: time.Now()}
}

func (b *Beta) decayLocked(now time.Time) {
	if b.halfLife <= 0 {
		return
	}
	dt := now.Sub(b.last)
	if dt <= 0 {
		return
	}
	b.last = now
	f := math.Exp2(-float64(dt) / float64(b.halfLife))
	b.alpha = priorAlpha + (b.alpha-priorAlpha)*f
	b.beta = priorBeta + (b.beta-priorBeta)*f
}

func (b *Beta) Observe(success bool, weight float64, now time.Time) {
	if weight <= 0 {
		return
	}
	b.mu.Lock()
	defer b.mu.Unlock()
	b.decayLocked(now)
	if success {
		b.alpha += weight
	} else {
		b.beta += weight
	}
}

func (b *Beta) Params(now time.Time) (float64, float64) {
	b.mu.Lock()
	defer b.mu.Unlock()
	b.decayLocked(now)
	return b.alpha, b.beta
}

func (b *Beta) Mean(now time.Time) float64 {
	a, c := b.Params(now)
	return a / (a + c)
}

func (b *Beta) Weight(now time.Time) float64 {
	a, c := b.Params(now)
	return a + c - priorAlpha - priorBeta
}

func (b *Beta) Sample(rng *rand.Rand, now time.Time) float64 {
	a, c := b.Params(now)
	x := sampleGamma(rng, a)
	y := sampleGamma(rng, c)
	if x+y == 0 {
		return 0.5
	}
	return x / (x + y)
}

func (b *Beta) Snapshot() (float64, float64) {
	b.mu.Lock()
	defer b.mu.Unlock()
	return b.alpha, b.beta
}

func (b *Beta) Restore(alpha, beta float64) {
	b.mu.Lock()
	b.alpha, b.beta, b.last = alpha, beta, time.Now()
	b.mu.Unlock()
}

func sampleGamma(rng *rand.Rand, shape float64) float64 {
	if shape <= 0 {
		return 0
	}
	if shape < 1 {
		return sampleGamma(rng, shape+1) * math.Pow(rng.Float64(), 1/shape)
	}
	d := shape - 1.0/3.0
	c := 1 / math.Sqrt(9*d)
	for {
		x := rng.NormFloat64()
		v := 1 + c*x
		if v <= 0 {
			continue
		}
		v = v * v * v
		u := rng.Float64()
		if u < 1-0.0331*x*x*x*x {
			return d * v
		}
		if math.Log(u) < 0.5*x*x+d*(1-v+math.Log(v)) {
			return d * v
		}
	}
}

// EWMA with a time constant rather than a sample count: probes do not arrive on
// a fixed cadence once a server starts timing out, and a count based average
// silently changes its meaning when they stop.
type EWMA struct {
	mu   sync.Mutex
	tau  time.Duration
	val  float64
	last time.Time
	set  bool
}

func NewEWMA(tau time.Duration) *EWMA { return &EWMA{tau: tau} }

func (e *EWMA) Add(v float64, now time.Time) {
	e.mu.Lock()
	defer e.mu.Unlock()
	if !e.set {
		e.val, e.last, e.set = v, now, true
		return
	}
	dt := now.Sub(e.last)
	if dt < 0 {
		dt = 0
	}
	e.last = now
	w := 1 - math.Exp(-float64(dt)/float64(e.tau))
	e.val += w * (v - e.val)
}

func (e *EWMA) Value() float64 {
	e.mu.Lock()
	defer e.mu.Unlock()
	return e.val
}

func (e *EWMA) Known() bool {
	e.mu.Lock()
	defer e.mu.Unlock()
	return e.set
}

// Accrual is the phi accrual failure detector. "Three misses and you are dead"
// is a threshold on a number nobody chose; phi is a continuous suspicion level
// derived from how surprising the current silence is given how regular the
// heartbeats have been, which means one slow network does not get the same
// verdict as one dead server.
type Accrual struct {
	mu      sync.Mutex
	samples []float64
	idx     int
	filled  bool
	last    time.Time
	minStd  float64
}

func NewAccrual(window int) *Accrual {
	if window < 8 {
		window = 8
	}
	return &Accrual{samples: make([]float64, window), minStd: 50}
}

func (a *Accrual) Heartbeat(now time.Time) {
	a.mu.Lock()
	defer a.mu.Unlock()
	if !a.last.IsZero() {
		ms := float64(now.Sub(a.last)) / float64(time.Millisecond)
		a.samples[a.idx] = ms
		a.idx = (a.idx + 1) % len(a.samples)
		if a.idx == 0 {
			a.filled = true
		}
	}
	a.last = now
}

func (a *Accrual) stats() (mean, std float64, n int) {
	count := len(a.samples)
	if !a.filled {
		count = a.idx
	}
	if count == 0 {
		return 0, 0, 0
	}
	for i := range count {
		mean += a.samples[i]
	}
	mean /= float64(count)
	for i := range count {
		d := a.samples[i] - mean
		std += d * d
	}
	std = math.Sqrt(std / float64(count))
	return mean, math.Max(std, a.minStd), count
}

func (a *Accrual) Phi(now time.Time) float64 {
	a.mu.Lock()
	defer a.mu.Unlock()

	if a.last.IsZero() {
		return 0
	}
	mean, std, n := a.stats()
	if n < 3 {
		return 0
	}
	elapsed := float64(now.Sub(a.last)) / float64(time.Millisecond)
	p := 1 - cdf(elapsed, mean, std)
	if p < 1e-12 {
		p = 1e-12
	}
	return -math.Log10(p)
}

func (a *Accrual) Reset() {
	a.mu.Lock()
	a.samples = make([]float64, len(a.samples))
	a.idx, a.filled = 0, false
	a.last = time.Time{}
	a.mu.Unlock()
}

func cdf(x, mean, std float64) float64 {
	return 0.5 * (1 + math.Erf((x-mean)/(std*math.Sqrt2)))
}
