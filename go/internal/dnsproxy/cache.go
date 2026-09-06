package dnsproxy

import (
	"strings"
	"sync"
	"time"

	"github.com/miekg/dns"
)

const (
	MaxTTL = 30 * time.Minute

	StaleGrace = time.Hour

	StaleTTL = 30 * time.Second
)

type entry struct {
	msg     *dns.Msg
	expires time.Time
}

type Cache struct {
	mu   sync.RWMutex
	seen map[string]*entry
}

func newCache() *Cache { return &Cache{seen: make(map[string]*entry)} }

func (c *Cache) Put(key string, msg *dns.Msg) {
	if msg == nil || msg.Rcode != dns.RcodeSuccess || msg.Truncated || len(msg.Answer) == 0 {
		return
	}

	ttl := msg.Answer[0].Header().Ttl
	for _, rr := range msg.Answer[1:] {
		if t := rr.Header().Ttl; t < ttl {
			ttl = t
		}
	}
	if ttl == 0 {
		return
	}

	cached := msg.Copy()
	cached.Extra = nil

	c.mu.Lock()
	c.seen[key] = &entry{
		msg:     cached,
		expires: time.Now().Add(min(time.Duration(ttl)*time.Second, MaxTTL)),
	}
	c.mu.Unlock()
}

func (c *Cache) Get(key string, r *dns.Msg) *dns.Msg {
	ent := c.lookup(key)
	if ent == nil {
		return nil
	}
	left := time.Until(ent.expires)
	if left <= 0 {
		return nil
	}
	return replyFrom(ent.msg, r, max(uint32(left/time.Second), 1))
}

func (c *Cache) Stale(key string, r *dns.Msg) *dns.Msg {
	ent := c.lookup(key)
	if ent == nil {
		return nil
	}
	if time.Now().After(ent.expires.Add(StaleGrace)) {
		c.mu.Lock()
		delete(c.seen, key)
		c.mu.Unlock()
		return nil
	}
	return replyFrom(ent.msg, r, uint32(StaleTTL/time.Second))
}

func (c *Cache) Sweep(now time.Time) {
	c.mu.Lock()
	for key, ent := range c.seen {
		if now.After(ent.expires.Add(StaleGrace)) {
			delete(c.seen, key)
		}
	}
	c.mu.Unlock()
}

func (c *Cache) Len() int {
	c.mu.RLock()
	defer c.mu.RUnlock()
	return len(c.seen)
}

func (c *Cache) lookup(key string) *entry {
	c.mu.RLock()
	defer c.mu.RUnlock()
	return c.seen[key]
}

func replyFrom(cached, r *dns.Msg, ttl uint32) *dns.Msg {
	resp := cached.Copy()
	resp.Id = r.Id
	resp.Response = true
	resp.Opcode = r.Opcode
	resp.RecursionDesired = r.RecursionDesired
	resp.CheckingDisabled = r.CheckingDisabled
	resp.RecursionAvailable = true
	resp.Question = []dns.Question{r.Question[0]}

	for _, rr := range resp.Answer {
		rr.Header().Ttl = ttl
		if strings.EqualFold(rr.Header().Name, r.Question[0].Name) {
			rr.Header().Name = r.Question[0].Name
		}
	}
	for _, rr := range resp.Ns {
		rr.Header().Ttl = ttl
	}
	if opt := r.IsEdns0(); opt != nil {
		resp.SetEdns0(opt.UDPSize(), opt.Do())
	}
	return resp
}
