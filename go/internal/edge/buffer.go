package edge

import (
	"sync"

	"unsafie/internal/bufpool"
)

type segment struct {
	buf  *[]byte
	r, w int
}

type recvBuf struct {
	mu       sync.Mutex
	queue    []segment
	size     int
	err      error
	messages bool
	signal   chan struct{}
}

func newRecvBuf(messages bool) *recvBuf {
	return &recvBuf{messages: messages, signal: make(chan struct{}, 1)}
}

func (b *recvBuf) wake() {
	select {
	case b.signal <- struct{}{}:
	default:
	}
}

func (b *recvBuf) push(p []byte) {
	b.mu.Lock()
	if b.err != nil {
		b.mu.Unlock()
		return
	}
	if b.messages {
		seg := segment{buf: bufpool.Chunks.Get()}
		if len(p) > len(*seg.buf) {
			bufpool.Chunks.Put(seg.buf)
			owned := make([]byte, len(p))
			seg = segment{buf: &owned}
		}
		seg.w = copy(*seg.buf, p)
		b.queue = append(b.queue, seg)
		b.size += seg.w
		b.mu.Unlock()
		b.wake()
		return
	}

	for len(p) > 0 {
		last := len(b.queue) - 1
		if last < 0 || b.queue[last].w == len(*b.queue[last].buf) {
			b.queue = append(b.queue, segment{buf: bufpool.Chunks.Get()})
			last++
		}
		seg := &b.queue[last]
		n := copy((*seg.buf)[seg.w:], p)
		seg.w += n
		b.size += n
		p = p[n:]
	}
	b.mu.Unlock()
	b.wake()
}

func (b *recvBuf) drop() {
	seg := b.queue[0]
	b.size -= seg.w - seg.r
	if cap(*seg.buf) == bufpool.ChunkSize {
		bufpool.Chunks.Put(seg.buf)
	}
	b.queue[0] = segment{}
	b.queue = b.queue[1:]
}

// A datagram that does not fit is truncated rather than split: half a packet is
// not a packet, and the next Read has to see the next one.
func (b *recvBuf) pull(p []byte) int {
	b.mu.Lock()
	defer b.mu.Unlock()

	if len(b.queue) == 0 {
		return 0
	}
	if b.messages {
		seg := b.queue[0]
		n := copy(p, (*seg.buf)[seg.r:seg.w])
		b.drop()
		return n
	}

	total := 0
	for total < len(p) && len(b.queue) > 0 {
		seg := &b.queue[0]
		n := copy(p[total:], (*seg.buf)[seg.r:seg.w])
		seg.r += n
		total += n
		b.size -= n
		if seg.r == seg.w {
			b.drop()
		}
	}
	return total
}

func (b *recvBuf) failure() error {
	b.mu.Lock()
	defer b.mu.Unlock()
	if b.size > 0 {
		return nil
	}
	return b.err
}

func (b *recvBuf) buffered() int {
	b.mu.Lock()
	defer b.mu.Unlock()
	return b.size
}

func (b *recvBuf) fail(err error) {
	b.mu.Lock()
	if b.err == nil {
		b.err = err
	}
	b.mu.Unlock()
	b.wake()
}

func (b *recvBuf) discard() {
	b.mu.Lock()
	for i := range b.queue {
		if b.queue[i].buf != nil && cap(*b.queue[i].buf) == bufpool.ChunkSize {
			bufpool.Chunks.Put(b.queue[i].buf)
		}
	}
	b.queue, b.size = nil, 0
	b.mu.Unlock()
}

type credit struct {
	mu     sync.Mutex
	n      int64
	closed bool
	signal chan struct{}
}

func newCredit(n int64) *credit {
	return &credit{n: n, signal: make(chan struct{}, 1)}
}

func (c *credit) add(n int64) {
	c.mu.Lock()
	c.n += n
	c.mu.Unlock()
	select {
	case c.signal <- struct{}{}:
	default:
	}
}

func (c *credit) close() {
	c.mu.Lock()
	c.closed = true
	c.mu.Unlock()
	select {
	case c.signal <- struct{}{}:
	default:
	}
}

func (c *credit) take(want int64) (int64, bool) {
	c.mu.Lock()
	defer c.mu.Unlock()
	if c.closed {
		return 0, false
	}
	if c.n <= 0 {
		return 0, true
	}
	n := min(want, c.n)
	c.n -= n
	return n, true
}

func (c *credit) takeExact(want int64) (int64, bool) {
	c.mu.Lock()
	defer c.mu.Unlock()
	if c.closed {
		return 0, false
	}
	if c.n < want {
		return 0, true
	}
	c.n -= want
	return want, true
}

func (c *credit) level() int64 {
	c.mu.Lock()
	defer c.mu.Unlock()
	return c.n
}
