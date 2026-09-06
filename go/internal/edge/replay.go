package edge

import "sync"

// ring keeps the tail of a byte stream so a broken leg can be picked up exactly
// where the peer stopped reading instead of where the socket stopped working.
type ring struct {
	mu   sync.Mutex
	buf  []byte
	base int64
	end  int64
	pos  int
	full bool
}

func newRing(size int) *ring { return &ring{buf: make([]byte, size)} }

func (r *ring) Append(p []byte) {
	r.mu.Lock()
	defer r.mu.Unlock()

	r.end += int64(len(p))
	if len(p) >= len(r.buf) {
		copy(r.buf, p[len(p)-len(r.buf):])
		r.pos, r.full = 0, true
		r.base = r.end - int64(len(r.buf))
		return
	}
	for len(p) > 0 {
		n := copy(r.buf[r.pos:], p)
		r.pos += n
		if r.pos == len(r.buf) {
			r.pos, r.full = 0, true
		}
		p = p[n:]
	}
	if r.full {
		r.base = r.end - int64(len(r.buf))
	}
}

func (r *ring) End() int64 {
	r.mu.Lock()
	defer r.mu.Unlock()
	return r.end
}

func (r *ring) Holds(off int64) bool {
	r.mu.Lock()
	defer r.mu.Unlock()
	return off >= r.base && off <= r.end
}

// Since copies out everything from an absolute offset. A false means the peer
// asked for bytes that have already scrolled out and the session cannot be
// honestly continued.
func (r *ring) Since(off int64) ([]byte, bool) {
	r.mu.Lock()
	defer r.mu.Unlock()

	if off < r.base || off > r.end {
		return nil, false
	}
	want := int(r.end - off)
	if want == 0 {
		return nil, true
	}

	out := make([]byte, want)
	start := r.pos - want
	if start >= 0 {
		copy(out, r.buf[start:r.pos])
		return out, true
	}
	head := -start
	copy(out, r.buf[len(r.buf)-head:])
	copy(out[head:], r.buf[:r.pos])
	return out, true
}

func (r *ring) Reset(at int64) {
	r.mu.Lock()
	r.base, r.end, r.pos, r.full = at, at, 0, false
	r.mu.Unlock()
}
