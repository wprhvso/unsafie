package netx

import (
	"context"
	"io"
	"net"
	"strings"
	"sync"
	"time"

	"unsafie/internal/bufpool"
)

type DialFunc func(ctx context.Context, network, address string) (net.Conn, error)

func Copy(dst io.Writer, src io.Reader) {
	buf := bufpool.Chunks.Get()
	defer bufpool.Chunks.Put(buf)

	_, _ = io.CopyBuffer(dst, src, *buf)
}

func Pipe(client net.Conn, clientRead io.Reader, upstream net.Conn, halfCloseWait time.Duration) {
	var wg sync.WaitGroup
	wg.Add(2)

	half := func(dst net.Conn, src io.Reader) {
		defer wg.Done()
		Copy(dst, src)

		cw, ok := dst.(interface{ CloseWrite() error })
		if !ok || cw.CloseWrite() != nil {
			_ = dst.Close()
			return
		}
		Linger(dst, halfCloseWait)
	}

	go half(upstream, clientRead)
	go half(client, upstream)
	wg.Wait()
}

func Linger(conn net.Conn, d time.Duration) {
	if l, ok := conn.(interface{ SetReadLinger(d time.Duration) }); ok {
		l.SetReadLinger(d)
		return
	}
	_ = conn.SetReadDeadline(time.Now().Add(d))
}

func SplitTarget(address string) (host, port string) {
	h, p, err := net.SplitHostPort(address)
	if err != nil {
		return strings.Trim(address, "[]"), ""
	}
	return strings.Trim(h, "[]"), p
}

func WithDefaultPort(host, port string) string {
	if _, _, err := net.SplitHostPort(host); err != nil {
		return net.JoinHostPort(host, port)
	}
	return host
}

func Listen(ctx context.Context, addr string) (net.Listener, error) {
	var lc net.ListenConfig

	ln, err := lc.Listen(ctx, "tcp", addr)
	if err != nil {
		return nil, err
	}
	go func() {
		<-ctx.Done()
		_ = ln.Close()
	}()
	return ln, nil
}
