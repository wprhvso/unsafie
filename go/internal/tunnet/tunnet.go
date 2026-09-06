package tunnet

import (
	"context"
	"errors"
	"fmt"
	"io"
	"net"
	"net/netip"
	"time"

	"gvisor.dev/gvisor/pkg/tcpip"
	"gvisor.dev/gvisor/pkg/tcpip/adapters/gonet"
	"gvisor.dev/gvisor/pkg/tcpip/header"
	"gvisor.dev/gvisor/pkg/tcpip/network/ipv4"
	"gvisor.dev/gvisor/pkg/tcpip/network/ipv6"
	"gvisor.dev/gvisor/pkg/tcpip/stack"
	"gvisor.dev/gvisor/pkg/tcpip/transport/icmp"
	"gvisor.dev/gvisor/pkg/tcpip/transport/tcp"
	"gvisor.dev/gvisor/pkg/tcpip/transport/udp"
	"gvisor.dev/gvisor/pkg/waiter"

	"unsafie/internal/bufpool"
	"unsafie/internal/logging"
	"unsafie/internal/netx"
	"unsafie/internal/socksproxy"
)

const (
	tunNICID = tcpip.NICID(1)

	tcpMaxInFlight       = 2 << 10
	tcpKeepaliveIdle     = 60 * time.Second
	tcpKeepaliveInterval = 30 * time.Second
	tcpKeepaliveCount    = 9

	udpIdleTimeout = 30 * time.Second

	UDPBufferSize = 65535
)

type Device interface {
	stack.LinkEndpoint

	Dead() <-chan struct{}
	Release()
}

var ErrDeviceGone = errors.New("the device stopped delivering packets")

func New(ctx context.Context, ep stack.LinkEndpoint, dial netx.DialFunc) (*stack.Stack, error) {
	s := stack.New(stack.Options{
		NetworkProtocols: []stack.NetworkProtocolFactory{
			ipv4.NewProtocol,
			ipv6.NewProtocol,
		},
		TransportProtocols: []stack.TransportProtocolFactory{
			tcp.NewProtocol,
			udp.NewProtocol,
			icmp.NewProtocol4,
			icmp.NewProtocol6,
		},
	})

	s.SetTransportProtocolHandler(tcp.ProtocolNumber, newTCPForwarder(ctx, s, dial).HandlePacket)
	s.SetTransportProtocolHandler(udp.ProtocolNumber, newUDPForwarder(ctx, s, dial).HandlePacket)

	if err := s.CreateNICWithOptions(tunNICID, ep, stack.NICOptions{}); err != nil {
		s.Close()
		return nil, fmt.Errorf("create NIC: %s", err)
	}

	if err := s.SetPromiscuousMode(tunNICID, true); err != nil {
		s.Close()
		return nil, fmt.Errorf("set promiscuous mode: %s", err)
	}
	if err := s.SetSpoofing(tunNICID, true); err != nil {
		s.Close()
		return nil, fmt.Errorf("set spoofing: %s", err)
	}

	s.SetRouteTable([]tcpip.Route{
		{Destination: header.IPv4EmptySubnet, NIC: tunNICID},
		{Destination: header.IPv6EmptySubnet, NIC: tunNICID},
	})

	if err := setStackOptions(s); err != nil {
		s.Close()
		return nil, err
	}
	return s, nil
}

func setStackOptions(s *stack.Stack) error {
	ttl := tcpip.DefaultTTLOption(64)
	for _, proto := range []tcpip.NetworkProtocolNumber{ipv4.ProtocolNumber, ipv6.ProtocolNumber} {
		if err := s.SetNetworkProtocolOption(proto, &ttl); err != nil {
			return fmt.Errorf("set default TTL: %s", err)
		}
		if err := s.SetForwardingDefaultAndAllNICs(proto, true); err != nil {
			return fmt.Errorf("set forwarding: %s", err)
		}
	}

	sndBuf := tcpip.TCPSendBufferSizeRangeOption{
		Min: tcp.MinBufferSize, Default: tcp.DefaultSendBufferSize, Max: tcp.MaxBufferSize,
	}
	rcvBuf := tcpip.TCPReceiveBufferSizeRangeOption{
		Min: tcp.MinBufferSize, Default: tcp.DefaultReceiveBufferSize, Max: tcp.MaxBufferSize,
	}
	congestion := tcpip.CongestionControlOption("reno")
	delay := tcpip.TCPDelayEnabled(false)
	moderate := tcpip.TCPModerateReceiveBufferOption(false)
	sack := tcpip.TCPSACKEnabled(true)
	recovery := tcpip.TCPRACKLossDetection

	opts := []tcpip.SettableTransportProtocolOption{
		&sndBuf, &rcvBuf, &congestion, &delay, &moderate, &sack, &recovery,
	}
	for _, opt := range opts {
		if err := s.SetTransportProtocolOption(tcp.ProtocolNumber, opt); err != nil {
			return fmt.Errorf("set TCP option %T: %s", opt, err)
		}
	}
	return nil
}

func newTCPForwarder(ctx context.Context, s *stack.Stack, dial netx.DialFunc) *tcp.Forwarder {
	return tcp.NewForwarder(s, 0, tcpMaxInFlight, func(r *tcp.ForwarderRequest) {
		var wq waiter.Queue

		ep, err := r.CreateEndpoint(&wq)
		if err != nil {
			r.Complete(true)
			return
		}
		defer r.Complete(false)

		setTCPSocketOptions(s, ep)

		id := r.ID()
		go pipeTCP(ctx, gonet.NewTCPConn(&wq, ep), endpointTarget(id), dial)
	})
}

func newUDPForwarder(ctx context.Context, s *stack.Stack, dial netx.DialFunc) *udp.Forwarder {
	return udp.NewForwarder(s, func(r *udp.ForwarderRequest) {
		var wq waiter.Queue

		ep, err := r.CreateEndpoint(&wq)
		if err != nil {
			return
		}

		id := r.ID()
		go pipeUDP(ctx, gonet.NewUDPConn(&wq, ep), endpointTarget(id), dial)
	})
}

func endpointTarget(id stack.TransportEndpointID) string {
	addr, _ := netip.AddrFromSlice(id.LocalAddress.AsSlice())
	return netip.AddrPortFrom(addr.Unmap(), id.LocalPort).String()
}

func setTCPSocketOptions(s *stack.Stack, ep tcpip.Endpoint) {
	ep.SocketOptions().SetKeepAlive(true)

	idle := tcpip.KeepaliveIdleOption(tcpKeepaliveIdle)
	_ = ep.SetSockOpt(&idle)
	interval := tcpip.KeepaliveIntervalOption(tcpKeepaliveInterval)
	_ = ep.SetSockOpt(&interval)
	_ = ep.SetSockOptInt(tcpip.KeepaliveCountOption, tcpKeepaliveCount)

	var snd tcpip.TCPSendBufferSizeRangeOption
	if err := s.TransportProtocolOption(header.TCPProtocolNumber, &snd); err == nil {
		ep.SocketOptions().SetSendBufferSize(int64(snd.Default), false)
	}
	var rcv tcpip.TCPReceiveBufferSizeRangeOption
	if err := s.TransportProtocolOption(header.TCPProtocolNumber, &rcv); err == nil {
		ep.SocketOptions().SetReceiveBufferSize(int64(rcv.Default), false)
	}
}

func pipeTCP(ctx context.Context, conn *gonet.TCPConn, target string, dial netx.DialFunc) {
	defer conn.Close()

	cc, err := dial(ctx, "tcp", target)
	if err != nil {
		logging.Infof("tun: dial %s: %v", target, err)
		return
	}
	defer cc.Close()

	netx.Pipe(conn, conn, cc, socksproxy.HalfCloseWait)
}

func pipeUDP(ctx context.Context, conn *gonet.UDPConn, target string, dial netx.DialFunc) {
	defer conn.Close()

	cc, err := dial(ctx, "udp", target)
	if err != nil {
		logging.Infof("tun: dial udp %s: %v", target, err)
		return
	}
	defer cc.Close()

	done := make(chan struct{}, 2)
	go func() { copyPackets(cc, conn); done <- struct{}{} }()
	go func() { copyPackets(conn, cc); done <- struct{}{} }()
	<-done
}

var udpBufPool = bufpool.New(UDPBufferSize)

func copyPackets(dst, src net.Conn) {
	bufp := udpBufPool.Get()
	defer udpBufPool.Put(bufp)

	buf := *bufp
	for {
		if err := src.SetReadDeadline(time.Now().Add(udpIdleTimeout)); err != nil {
			return
		}
		n, err := src.Read(buf)
		if n > 0 {
			if _, werr := dst.Write(buf[:n]); werr != nil {
				return
			}
		}
		if errors.Is(err, io.ErrShortBuffer) {
			continue
		}
		if err != nil {
			return
		}
	}
}
