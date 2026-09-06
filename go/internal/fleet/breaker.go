package fleet

import (
	"sync"
	"time"

	"unsafie/internal/backoff"
)

type State uint8

const (
	StateClosed State = iota
	StateOpen
	StateHalfOpen
)

func (s State) String() string {
	switch s {
	case StateOpen:
		return "open"
	case StateHalfOpen:
		return "half-open"
	default:
		return "closed"
	}
}

// Breaker keeps a server that is plainly down from being asked once per new
// connection. It trips on consecutive failures rather than on a ratio: a server
// that fails one call in five is not down, it is degraded, and degraded is what
// the posterior is for.
type Breaker struct {
	mu sync.Mutex

	state       State
	consecutive int
	trip        int
	openedAt    time.Time
	cooldown    time.Duration
	delay       *backoff.Jitter
	probing     bool
	trips       uint64
}

func NewBreaker(trip int, base, maximum time.Duration) *Breaker {
	return &Breaker{state: StateClosed, trip: trip, delay: backoff.New(base, maximum)}
}

// Allow answers whether a call may go out, and whether it is the one probe that
// a half open breaker permits.
func (b *Breaker) Allow(now time.Time) bool {
	b.mu.Lock()
	defer b.mu.Unlock()

	switch b.state {
	case StateClosed:
		return true
	case StateOpen:
		if now.Sub(b.openedAt) < b.cooldown {
			return false
		}
		b.state = StateHalfOpen
		b.probing = true
		return true
	default:
		if b.probing {
			return false
		}
		b.probing = true
		return true
	}
}

// Force is the escape hatch the picker uses when every server is open: it is
// better to try the least hopeless one than to answer "no route" to a user who
// is staring at a blank page.
func (b *Breaker) Force() {
	b.mu.Lock()
	b.probing = false
	b.mu.Unlock()
}

func (b *Breaker) Success(now time.Time) {
	b.mu.Lock()
	defer b.mu.Unlock()
	b.consecutive = 0
	b.probing = false
	if b.state != StateClosed {
		b.state = StateClosed
		b.delay.Reset()
	}
}

func (b *Breaker) Failure(now time.Time) {
	b.mu.Lock()
	defer b.mu.Unlock()

	b.consecutive++
	b.probing = false
	if b.state == StateHalfOpen || b.consecutive >= b.trip {
		if b.state != StateOpen {
			b.trips++
		}
		b.state = StateOpen
		b.openedAt = now
		b.cooldown = b.delay.Next()
	}
}

func (b *Breaker) State() State {
	b.mu.Lock()
	defer b.mu.Unlock()
	return b.state
}

func (b *Breaker) Trips() uint64 {
	b.mu.Lock()
	defer b.mu.Unlock()
	return b.trips
}

func (b *Breaker) RetryIn(now time.Time) time.Duration {
	b.mu.Lock()
	defer b.mu.Unlock()
	if b.state != StateOpen {
		return 0
	}
	left := b.cooldown - now.Sub(b.openedAt)
	if left < 0 {
		return 0
	}
	return left
}
