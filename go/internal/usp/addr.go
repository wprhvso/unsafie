package usp

import (
	"encoding/binary"
	"errors"
	"net"
	"net/netip"
	"strconv"
	"strings"
)

type AddrKind uint8

const (
	AddrIPv4   AddrKind = 0x01
	AddrIPv6   AddrKind = 0x02
	AddrDomain AddrKind = 0x03
)

var (
	ErrBadAddr     = errors.New("usp: malformed address")
	ErrLongDomain  = errors.New("usp: domain longer than 255 bytes")
	ErrEmptyTarget = errors.New("usp: empty target")
)

type Addr struct {
	Kind   AddrKind
	IP     netip.Addr
	Domain string
	Port   uint16
}

func (a Addr) Host() string {
	if a.Kind == AddrDomain {
		return a.Domain
	}
	return a.IP.String()
}

func (a Addr) String() string {
	return net.JoinHostPort(a.Host(), strconv.Itoa(int(a.Port)))
}

func (a Addr) Size() int {
	switch a.Kind {
	case AddrIPv4:
		return 1 + 4 + 2
	case AddrIPv6:
		return 1 + 16 + 2
	default:
		return 1 + 1 + len(a.Domain) + 2
	}
}

func ParseAddr(target string) (Addr, error) {
	host, portText, err := net.SplitHostPort(target)
	if err != nil {
		return Addr{}, ErrBadAddr
	}
	host = strings.Trim(host, "[]")
	if host == "" {
		return Addr{}, ErrEmptyTarget
	}
	port, err := strconv.ParseUint(portText, 10, 16)
	if err != nil {
		return Addr{}, ErrBadAddr
	}

	a := Addr{Port: uint16(port)}
	if ip, err := netip.ParseAddr(host); err == nil {
		ip = ip.Unmap()
		a.IP = ip
		if ip.Is4() {
			a.Kind = AddrIPv4
		} else {
			a.Kind = AddrIPv6
		}
		return a, nil
	}

	host = strings.TrimSuffix(host, ".")
	if len(host) > 255 {
		return Addr{}, ErrLongDomain
	}
	a.Kind = AddrDomain
	a.Domain = host
	return a, nil
}

func AppendAddr(dst []byte, a Addr) []byte {
	switch a.Kind {
	case AddrIPv4:
		v4 := a.IP.As4()
		dst = append(dst, byte(AddrIPv4))
		dst = append(dst, v4[:]...)
	case AddrIPv6:
		v6 := a.IP.As16()
		dst = append(dst, byte(AddrIPv6))
		dst = append(dst, v6[:]...)
	default:
		dst = append(dst, byte(AddrDomain), byte(len(a.Domain)))
		dst = append(dst, a.Domain...)
	}
	return binary.BigEndian.AppendUint16(dst, a.Port)
}

func DecodeAddr(b []byte) (Addr, []byte, error) {
	if len(b) < 1 {
		return Addr{}, nil, ErrBadAddr
	}

	var a Addr
	kind := AddrKind(b[0])
	b = b[1:]

	switch kind {
	case AddrIPv4:
		if len(b) < 4 {
			return Addr{}, nil, ErrBadAddr
		}
		a.Kind, a.IP = AddrIPv4, netip.AddrFrom4([4]byte(b[:4]))
		b = b[4:]
	case AddrIPv6:
		if len(b) < 16 {
			return Addr{}, nil, ErrBadAddr
		}
		a.Kind, a.IP = AddrIPv6, netip.AddrFrom16([16]byte(b[:16]))
		b = b[16:]
	case AddrDomain:
		if len(b) < 1 {
			return Addr{}, nil, ErrBadAddr
		}
		n := int(b[0])
		if len(b) < 1+n {
			return Addr{}, nil, ErrBadAddr
		}
		a.Kind, a.Domain = AddrDomain, string(b[1:1+n])
		b = b[1+n:]
	default:
		return Addr{}, nil, ErrBadAddr
	}

	if len(b) < 2 {
		return Addr{}, nil, ErrBadAddr
	}
	a.Port = binary.BigEndian.Uint16(b)
	return a, b[2:], nil
}
