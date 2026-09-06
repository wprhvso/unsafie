package socksproxy

import (
	"bufio"
	"context"
	"encoding/binary"
	"errors"
	"io"
	"net"
	"net/http"
	"strconv"
	"time"

	"unsafie/internal/logging"
	"unsafie/internal/netx"
)

const (
	socks5Version    = 0x05
	socks5NoAuth     = 0x00
	socks5CmdConnect = 0x01

	socks5AddrIPv4   = 0x01
	socks5AddrDomain = 0x03
	socks5AddrIPv6   = 0x04

	socks5OK               = 0x00
	socks5GeneralFailure   = 0x01
	socks5HostUnreachable  = 0x04
	socks5CmdNotSupported  = 0x07
	socks5AddrNotSupported = 0x08
)

const (
	HalfCloseWait    = 60 * time.Second
	acceptRetryDelay = 100 * time.Millisecond
	HandshakeTimeout = 30 * time.Second
)

type Server struct {
	ctx       context.Context
	dial      netx.DialFunc
	handshake time.Duration
}

func New(ctx context.Context, dial netx.DialFunc) *Server {
	return &Server{ctx: ctx, dial: dial, handshake: HandshakeTimeout}
}

func (p *Server) Serve(ln net.Listener) {
	logging.Infof("Local proxy listening on %s", ln.Addr())

	for {
		conn, err := ln.Accept()
		if err == nil {
			go p.handleConn(conn)
			continue
		}

		if errors.Is(err, net.ErrClosed) || p.ctx.Err() != nil {
			return
		}
		logging.Infof("Local proxy: accept failed: %v", err)

		select {
		case <-p.ctx.Done():
			return
		case <-time.After(acceptRetryDelay):
		}
	}
}

func (p *Server) handleConn(conn net.Conn) {
	defer conn.Close()

	_ = conn.SetDeadline(time.Now().Add(p.handshake))

	br := bufio.NewReader(conn)
	head, err := br.Peek(1)
	if err != nil {
		return
	}

	if head[0] == socks5Version {
		p.serveSOCKS5(conn, br)
		return
	}
	p.serveHTTPProxy(conn, br)
}

func (p *Server) serveSOCKS5(conn net.Conn, br *bufio.Reader) {
	var greeting [2]byte
	if _, err := io.ReadFull(br, greeting[:]); err != nil {
		return
	}
	if _, err := io.CopyN(io.Discard, br, int64(greeting[1])); err != nil {
		return
	}
	if _, err := conn.Write([]byte{socks5Version, socks5NoAuth}); err != nil {
		return
	}

	var head [4]byte
	if _, err := io.ReadFull(br, head[:]); err != nil {
		return
	}
	if head[0] != socks5Version {
		return
	}

	target, err := readSocks5Addr(br, head[3])
	if err != nil {
		_ = writeSocks5Reply(conn, socks5AddrNotSupported)
		return
	}
	if head[1] != socks5CmdConnect {
		_ = writeSocks5Reply(conn, socks5CmdNotSupported)
		return
	}

	cc, err := p.dial(p.ctx, "tcp", target)
	if err != nil {
		logging.Infof("SOCKS5 connect to %s failed: %v", target, err)
		_ = writeSocks5Reply(conn, socks5ReplyCode(err))
		return
	}
	defer cc.Close()

	if err := writeSocks5Reply(conn, socks5OK); err != nil {
		return
	}

	_ = conn.SetDeadline(time.Time{})
	netx.Pipe(conn, br, cc, HalfCloseWait)
}

func readSocks5Addr(r io.Reader, atyp byte) (string, error) {
	var host string

	switch atyp {
	case socks5AddrIPv4:
		var buf [4]byte
		if _, err := io.ReadFull(r, buf[:]); err != nil {
			return "", err
		}
		host = net.IP(buf[:]).String()
	case socks5AddrIPv6:
		var buf [16]byte
		if _, err := io.ReadFull(r, buf[:]); err != nil {
			return "", err
		}
		host = net.IP(buf[:]).String()
	case socks5AddrDomain:
		var size [1]byte
		if _, err := io.ReadFull(r, size[:]); err != nil {
			return "", err
		}
		buf := make([]byte, size[0])
		if _, err := io.ReadFull(r, buf); err != nil {
			return "", err
		}
		host = string(buf)
	default:
		return "", errors.New("socks5: unknown address type")
	}

	var port [2]byte
	if _, err := io.ReadFull(r, port[:]); err != nil {
		return "", err
	}
	return net.JoinHostPort(host, strconv.Itoa(int(binary.BigEndian.Uint16(port[:])))), nil
}

func writeSocks5Reply(w io.Writer, code byte) error {
	_, err := w.Write([]byte{socks5Version, code, 0x00, socks5AddrIPv4, 0, 0, 0, 0, 0, 0})
	return err
}

func socks5ReplyCode(err error) byte {
	var ne net.Error
	if errors.As(err, &ne) && ne.Timeout() {
		return socks5HostUnreachable
	}
	return socks5GeneralFailure
}

func (p *Server) serveHTTPProxy(conn net.Conn, br *bufio.Reader) {
	req, err := http.ReadRequest(br)
	if err != nil {
		return
	}

	if req.Method == http.MethodConnect {
		p.proxyConnect(conn, br, req)
		return
	}

	if req.URL.Host == "" {
		_, _ = io.WriteString(conn, "HTTP/1.1 400 Bad Request\r\n\r\n")
		return
	}

	cc, err := p.dial(p.ctx, "tcp", netx.WithDefaultPort(req.URL.Host, "80"))
	if err != nil {
		logging.Infof("HTTP proxy to %s failed: %v", req.URL.Host, err)
		_, _ = io.WriteString(conn, "HTTP/1.1 502 Bad Gateway\r\n\r\n")
		return
	}
	defer cc.Close()

	req.Header.Del("Proxy-Connection")
	req.Header.Del("Proxy-Authorization")
	req.Close = true

	_ = conn.SetDeadline(time.Time{})

	if err := req.Write(cc); err != nil {
		return
	}
	netx.Pipe(conn, br, cc, HalfCloseWait)
}

func (p *Server) proxyConnect(conn net.Conn, br *bufio.Reader, req *http.Request) {
	target := netx.WithDefaultPort(req.Host, "443")

	cc, err := p.dial(p.ctx, "tcp", target)
	if err != nil {
		logging.Infof("HTTP CONNECT to %s failed: %v", target, err)
		_, _ = io.WriteString(conn, "HTTP/1.1 502 Bad Gateway\r\n\r\n")
		return
	}
	defer cc.Close()

	if _, err := io.WriteString(conn, "HTTP/1.1 200 Connection established\r\n\r\n"); err != nil {
		return
	}

	_ = conn.SetDeadline(time.Time{})
	netx.Pipe(conn, br, cc, HalfCloseWait)
}
