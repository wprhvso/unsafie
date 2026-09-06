package usp

import (
	"encoding/binary"
	"errors"
	"net/netip"
)

const (
	tagVersion uint16 = 0x0001
	tagNonce   uint16 = 0x0002
	tagStreamW uint16 = 0x0003
	tagSessW   uint16 = 0x0004
	tagFeature uint16 = 0x0005
	tagTime    uint16 = 0x0006
	tagResume  uint16 = 0x0007
	tagDownOff uint16 = 0x0008
	tagLabel   uint16 = 0x0009
	tagWire    uint16 = 0x000A

	tagSession   uint16 = 0x8001
	tagRegion    uint16 = 0x8002
	tagCountry   uint16 = 0x8003
	tagASN       uint16 = 0x8004
	tagExitIP    uint16 = 0x8005
	tagKeepalive uint16 = 0x8006
	tagMaxStream uint16 = 0x8007
	tagReplay    uint16 = 0x8008
	tagResumed   uint16 = 0x8009
	tagLoad      uint16 = 0x800A
)

const (
	FeatureUDP uint32 = 1 << iota
	FeatureResume
	FeatureIPv6
	FeatureHappyEyeballs
	FeatureExitDNS
	FeatureStats
	FeaturePadding
)

const MaxHelloSize = 4 << 10

var (
	ErrBadHello  = errors.New("usp: malformed hello")
	ErrVersion   = errors.New("usp: unsupported protocol version")
	ErrHelloSize = errors.New("usp: hello too large")
)

type tlv struct{ buf []byte }

func (t *tlv) u8(tag uint16, v uint8)   { t.raw(tag, []byte{v}) }
func (t *tlv) u16(tag uint16, v uint16) { t.raw(tag, binary.BigEndian.AppendUint16(nil, v)) }
func (t *tlv) u32(tag uint16, v uint32) { t.raw(tag, binary.BigEndian.AppendUint32(nil, v)) }
func (t *tlv) u64(tag uint16, v uint64) { t.raw(tag, binary.BigEndian.AppendUint64(nil, v)) }
func (t *tlv) str(tag uint16, v string) {
	if v != "" {
		t.raw(tag, []byte(v))
	}
}

func (t *tlv) raw(tag uint16, v []byte) {
	if len(v) == 0 {
		return
	}
	t.buf = binary.BigEndian.AppendUint16(t.buf, tag)
	t.buf = binary.BigEndian.AppendUint16(t.buf, uint16(len(v)))
	t.buf = append(t.buf, v...)
}

func walk(b []byte, fn func(tag uint16, v []byte) error) error {
	for len(b) > 0 {
		if len(b) < 4 {
			return ErrBadHello
		}
		tag := binary.BigEndian.Uint16(b)
		n := int(binary.BigEndian.Uint16(b[2:]))
		if len(b) < 4+n {
			return ErrBadHello
		}
		if err := fn(tag, b[4:4+n]); err != nil {
			return err
		}
		b = b[4+n:]
	}
	return nil
}

func be32(v []byte) uint32 {
	if len(v) != 4 {
		return 0
	}
	return binary.BigEndian.Uint32(v)
}

func be64(v []byte) uint64 {
	if len(v) != 8 {
		return 0
	}
	return binary.BigEndian.Uint64(v)
}

type ClientHello struct {
	Version       uint8
	Nonce         [16]byte
	StreamWindow  uint32
	SessionWindow uint32
	Features      uint32
	SentAtMicros  uint64
	ResumeSession string
	ResumeDownAt  uint64
	Label         string
	Wire          string
}

func (h ClientHello) Encode() []byte {
	var t tlv
	t.u8(tagVersion, Version)
	t.raw(tagNonce, h.Nonce[:])
	t.u32(tagStreamW, h.StreamWindow)
	t.u32(tagSessW, h.SessionWindow)
	t.u32(tagFeature, h.Features)
	t.u64(tagTime, h.SentAtMicros)
	t.str(tagResume, h.ResumeSession)
	t.u64(tagDownOff, h.ResumeDownAt)
	t.str(tagLabel, h.Label)
	t.str(tagWire, h.Wire)
	return t.buf
}

func DecodeClientHello(b []byte) (ClientHello, error) {
	var h ClientHello
	if len(b) > MaxHelloSize {
		return h, ErrHelloSize
	}
	err := walk(b, func(tag uint16, v []byte) error {
		switch tag {
		case tagVersion:
			if len(v) == 1 {
				h.Version = v[0]
			}
		case tagNonce:
			copy(h.Nonce[:], v)
		case tagStreamW:
			h.StreamWindow = be32(v)
		case tagSessW:
			h.SessionWindow = be32(v)
		case tagFeature:
			h.Features = be32(v)
		case tagTime:
			h.SentAtMicros = be64(v)
		case tagResume:
			h.ResumeSession = string(v)
		case tagDownOff:
			h.ResumeDownAt = be64(v)
		case tagLabel:
			h.Label = string(v)
		case tagWire:
			h.Wire = string(v)
		}
		return nil
	})
	if err != nil {
		return h, err
	}
	if h.Version != Version {
		return h, ErrVersion
	}
	return h, nil
}

type ServerHello struct {
	Version       uint8
	Session       string
	StreamWindow  uint32
	SessionWindow uint32
	Features      uint32
	SentAtMicros  uint64
	Region        string
	Country       string
	ASN           uint32
	ExitIP        netip.Addr
	KeepaliveMS   uint32
	MaxStreams    uint16
	ReplayBytes   uint32
	Resumed       bool
	LoadPermille  uint16
}

func (h ServerHello) Encode() []byte {
	var t tlv
	t.u8(tagVersion, Version)
	t.str(tagSession, h.Session)
	t.u32(tagStreamW, h.StreamWindow)
	t.u32(tagSessW, h.SessionWindow)
	t.u32(tagFeature, h.Features)
	t.u64(tagTime, h.SentAtMicros)
	t.str(tagRegion, h.Region)
	t.str(tagCountry, h.Country)
	t.u32(tagASN, h.ASN)
	if h.ExitIP.IsValid() {
		ip := h.ExitIP.AsSlice()
		t.raw(tagExitIP, ip)
	}
	t.u32(tagKeepalive, h.KeepaliveMS)
	t.u16(tagMaxStream, h.MaxStreams)
	t.u32(tagReplay, h.ReplayBytes)
	if h.Resumed {
		t.u8(tagResumed, 1)
	}
	t.u16(tagLoad, h.LoadPermille)
	return t.buf
}

func DecodeServerHello(b []byte) (ServerHello, error) {
	var h ServerHello
	if len(b) > MaxHelloSize {
		return h, ErrHelloSize
	}
	err := walk(b, func(tag uint16, v []byte) error {
		switch tag {
		case tagVersion:
			if len(v) == 1 {
				h.Version = v[0]
			}
		case tagSession:
			h.Session = string(v)
		case tagStreamW:
			h.StreamWindow = be32(v)
		case tagSessW:
			h.SessionWindow = be32(v)
		case tagFeature:
			h.Features = be32(v)
		case tagTime:
			h.SentAtMicros = be64(v)
		case tagRegion:
			h.Region = string(v)
		case tagCountry:
			h.Country = string(v)
		case tagASN:
			h.ASN = be32(v)
		case tagExitIP:
			if addr, ok := netip.AddrFromSlice(v); ok {
				h.ExitIP = addr.Unmap()
			}
		case tagKeepalive:
			h.KeepaliveMS = be32(v)
		case tagMaxStream:
			if len(v) == 2 {
				h.MaxStreams = binary.BigEndian.Uint16(v)
			}
		case tagReplay:
			h.ReplayBytes = be32(v)
		case tagResumed:
			h.Resumed = len(v) == 1 && v[0] != 0
		case tagLoad:
			if len(v) == 2 {
				h.LoadPermille = binary.BigEndian.Uint16(v)
			}
		}
		return nil
	})
	if err != nil {
		return h, err
	}
	if h.Version != Version {
		return h, ErrVersion
	}
	if h.Session == "" {
		return h, ErrBadHello
	}
	return h, nil
}
