package chrome

import (
	"context"
	"crypto/tls"
	"errors"
	"net"
	"net/http"
	"time"

	"github.com/quic-go/quic-go"
	"github.com/quic-go/quic-go/http3"
)

var errNoUDP = errors.New("chrome: no UDP socket factory for QUIC")

func (w *Wire) newH3() http.RoundTripper {
	p := w.profile
	return &http3.Transport{
		TLSClientConfig: &tls.Config{
			ServerName:         w.opts.Host,
			NextProtos:         []string{"h3"},
			InsecureSkipVerify: w.opts.Insecure, //nolint:gosec // controlled by the caller, off by default
			RootCAs:            w.opts.RootCAs,
			ClientSessionCache: tls.NewLRUClientSessionCache(32),
			MinVersion:         tls.VersionTLS13,
		},
		QUICConfig: &quic.Config{
			Versions:                       []quic.Version{quic.Version1},
			MaxIdleTimeout:                 time.Duration(p.QUICMaxIdleMS) * time.Millisecond,
			InitialStreamReceiveWindow:     p.QUICStreamWindow,
			MaxStreamReceiveWindow:         p.QUICStreamWindow * 4,
			InitialConnectionReceiveWindow: p.QUICConnWindow,
			MaxConnectionReceiveWindow:     p.QUICConnWindow * 4,
			MaxIncomingStreams:             p.QUICMaxStreams,
			InitialPacketSize:              p.QUICMaxDatagramSize,
			KeepAlivePeriod:                15 * time.Second,
			Allow0RTT:                      true,
		},
		Dial:               w.dialQUIC,
		DisableCompression: true,
	}
}

// dialQUIC keeps QUIC on the same leash as everything else: the address comes
// from the client's own resolver rather than the system one, and the socket
// comes from the platform so it is marked to stay outside the tunnel it is
// being used to build.
func (w *Wire) dialQUIC(ctx context.Context, addr string, tlsCfg *tls.Config, cfg *quic.Config) (*quic.Conn, error) {
	if w.opts.ListenUDP == nil {
		return nil, errNoUDP
	}

	target, err := w.udpTarget(ctx, addr)
	if err != nil {
		return nil, err
	}

	pconn, err := w.opts.ListenUDP(ctx)
	if err != nil {
		return nil, err
	}

	conn, err := quic.DialEarly(ctx, pconn, target, tlsCfg, cfg)
	if err != nil {
		_ = pconn.Close()
		return nil, err
	}
	go func() {
		<-conn.Context().Done()
		_ = pconn.Close()
	}()
	return conn, nil
}

func (w *Wire) udpTarget(ctx context.Context, addr string) (*net.UDPAddr, error) {
	host, port, err := net.SplitHostPort(addr)
	if err != nil {
		host, port = addr, w.opts.Port
	}
	if w.opts.ResolveUDP != nil {
		if resolved, err := w.opts.ResolveUDP(ctx, host, port); err == nil {
			return resolved, nil
		} else if !errors.Is(err, errNoAddress) {
			return nil, err
		}
	}
	return net.ResolveUDPAddr("udp", net.JoinHostPort(host, port))
}

var errNoAddress = errors.New("chrome: no known address")

// ErrNoAddress lets the caller's resolver say "I have nothing cached" without
// that being a failure: falling back to the system resolver is fine for a
// hostname the client is built with, it is only never the first choice.
var ErrNoAddress = errNoAddress
