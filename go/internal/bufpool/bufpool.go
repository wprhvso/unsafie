package bufpool

import "sync"

const ChunkSize = 64 * 1024

var Chunks = New(ChunkSize)

type Pool struct {
	size int
	pool sync.Pool
}

func New(size int) *Pool {
	p := &Pool{size: size}
	p.pool.New = func() any { return p.alloc() }
	return p
}

func (p *Pool) alloc() *[]byte {
	b := make([]byte, p.size)
	return &b
}

func (p *Pool) Get() *[]byte {
	if buf, ok := p.pool.Get().(*[]byte); ok {
		return buf
	}
	return p.alloc()
}

func (p *Pool) Put(buf *[]byte) { p.pool.Put(buf) }
