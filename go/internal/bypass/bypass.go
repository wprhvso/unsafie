package bypass

import (
	"net/netip"
	"sync"
	"time"
)

type Set struct {
	ttl time.Duration

	mu   sync.RWMutex
	seen map[netip.Addr]time.Time
}

func New(ttl time.Duration) *Set {
	return &Set{ttl: ttl, seen: make(map[netip.Addr]time.Time)}
}

func (s *Set) Learn(addr netip.Addr) {
	s.mu.Lock()
	s.seen[addr] = time.Now().Add(s.ttl)
	s.mu.Unlock()
}

func (s *Set) Has(addr netip.Addr) bool {
	s.mu.RLock()
	expires, ok := s.seen[addr]
	s.mu.RUnlock()
	if !ok {
		return false
	}
	if time.Now().Before(expires) {
		return true
	}

	s.mu.Lock()
	if expires, ok := s.seen[addr]; ok && !time.Now().Before(expires) {
		delete(s.seen, addr)
	}
	s.mu.Unlock()
	return false
}

func (s *Set) Sweep(now time.Time) {
	s.mu.Lock()
	for addr, expires := range s.seen {
		if !now.Before(expires) {
			delete(s.seen, addr)
		}
	}
	s.mu.Unlock()
}

func (s *Set) Len() int {
	s.mu.RLock()
	defer s.mu.RUnlock()
	return len(s.seen)
}
