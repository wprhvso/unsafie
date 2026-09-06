package rules

import (
	"bytes"
	"encoding/binary"
	"errors"
	"fmt"
	"net/netip"
	"time"
)

var (
	ErrTooSmall    = errors.New("rules: data too small")
	ErrBadMagic    = errors.New("rules: bad magic")
	ErrBadVersion  = errors.New("rules: unsupported version")
	ErrOutOfBounds = errors.New("rules: section out of bounds")
)

type strTable struct {
	offsets []byte
	blob    []byte
	count   int
}

func checkOffsets(offsets []byte, blobLen int) error {
	prev := uint32(0)
	for i := 0; i+4 <= len(offsets); i += 4 {
		v := order.Uint32(offsets[i:])
		if v < prev || uint64(v) > uint64(blobLen) {
			return ErrOutOfBounds
		}
		prev = v
	}
	return nil
}

func (t strTable) at(i int) []byte {
	lo := order.Uint32(t.offsets[i*4:])
	hi := order.Uint32(t.offsets[i*4+4:])
	return t.blob[lo:hi]
}

type Set struct {
	generated time.Time
	hash      [32]byte

	ipv4  []byte
	ipv4N int
	ipv6  []byte
	ipv6N int

	suffix  strTable
	exact   strTable
	keyword strTable
}

func Load(data []byte) (*Set, error) {
	if len(data) < HeaderSize {
		return nil, ErrTooSmall
	}
	if string(data[offMagic:offMagic+8]) != Magic {
		return nil, ErrBadMagic
	}
	if v := order.Uint32(data[offVersion:]); v != Version {
		return nil, fmt.Errorf("%w: got %d want %d", ErrBadVersion, v, Version)
	}

	s := &Set{}
	s.generated = time.Unix(int64(order.Uint64(data[offGenerated:])), 0)
	copy(s.hash[:], data[offHash:offHash+32])

	slice := func(off, length uint64) ([]byte, error) {
		if off+length > uint64(len(data)) {
			return nil, ErrOutOfBounds
		}
		return data[off : off+length], nil
	}

	loadTable := func(tableOff, countOff, blobOff, blobLenOff int) (strTable, error) {
		var t strTable
		c := uint64(order.Uint32(data[countOff:]))
		o, err := slice(uint64(order.Uint32(data[tableOff:])), (c+1)*4)
		if err != nil {
			return t, err
		}
		b, err := slice(uint64(order.Uint32(data[blobOff:])), uint64(order.Uint32(data[blobLenOff:])))
		if err != nil {
			return t, err
		}
		if err := checkOffsets(o, len(b)); err != nil {
			return t, err
		}
		t.offsets = o
		t.blob = b
		t.count = int(c)
		return t, nil
	}

	var err error

	n4 := uint64(order.Uint32(data[offIPv4Count:]))
	if s.ipv4, err = slice(uint64(order.Uint32(data[offIPv4Off:])), n4*IPv4RecordSize); err != nil {
		return nil, err
	}
	s.ipv4N = int(n4)

	n6 := uint64(order.Uint32(data[offIPv6Count:]))
	if s.ipv6, err = slice(uint64(order.Uint32(data[offIPv6Off:])), n6*IPv6RecordSize); err != nil {
		return nil, err
	}
	s.ipv6N = int(n6)

	if s.suffix, err = loadTable(offSufTable, offSufCount, offSufBlob, offSufBlobLen); err != nil {
		return nil, err
	}
	if s.exact, err = loadTable(offExcTable, offExcCount, offExcBlob, offExcBlobLen); err != nil {
		return nil, err
	}
	if s.keyword, err = loadTable(offKwTable, offKwCount, offKwBlob, offKwBlobLen); err != nil {
		return nil, err
	}

	return s, nil
}

func (s *Set) Generated() time.Time { return s.generated }
func (s *Set) Hash() [32]byte       { return s.hash }

func (s *Set) Stats() (ipv4, ipv6, suffix, exact, keyword int) {
	return s.ipv4N, s.ipv6N, s.suffix.count, s.exact.count, s.keyword.count
}

func (s *Set) LookupIP(addr netip.Addr) bool {
	if !addr.IsValid() {
		return false
	}
	if addr.Is4In6() {
		addr = addr.Unmap()
	}
	if addr.Is4() {
		return s.lookup4(addr)
	}
	return s.lookup6(addr)
}

func (s *Set) lookup4(addr netip.Addr) bool {
	if s.ipv4N == 0 {
		return false
	}
	b := addr.As4()
	v := binary.BigEndian.Uint32(b[:])

	lo, hi := 0, s.ipv4N
	for lo < hi {
		mid := int(uint(lo+hi) >> 1)
		if order.Uint32(s.ipv4[mid*IPv4RecordSize:]) <= v {
			lo = mid + 1
		} else {
			hi = mid
		}
	}
	if lo == 0 {
		return false
	}
	rec := s.ipv4[(lo-1)*IPv4RecordSize:]
	return v <= order.Uint32(rec[4:])
}

func (s *Set) lookup6(addr netip.Addr) bool {
	if s.ipv6N == 0 {
		return false
	}
	a := addr.As16()

	lo, hi := 0, s.ipv6N
	for lo < hi {
		mid := int(uint(lo+hi) >> 1)
		start := s.ipv6[mid*IPv6RecordSize : mid*IPv6RecordSize+16]
		if bytes.Compare(start, a[:]) <= 0 {
			lo = mid + 1
		} else {
			hi = mid
		}
	}
	if lo == 0 {
		return false
	}
	end := s.ipv6[(lo-1)*IPv6RecordSize+16 : lo*IPv6RecordSize]
	return bytes.Compare(a[:], end) <= 0
}

func (s *Set) LookupDomain(host string) bool {
	h, ok := normalize(host)
	if !ok {
		return false
	}
	if s.exact.count > 0 && searchTable(s.exact, h) {
		return true
	}
	if s.suffix.count > 0 {
		for i := 0; ; {
			if searchTable(s.suffix, h[i:]) {
				return true
			}
			j := indexByteFrom(h, '.', i)
			if j < 0 {
				break
			}
			i = j + 1
		}
	}
	for i := range s.keyword.count {
		if containsBytes(h, s.keyword.at(i)) {
			return true
		}
	}
	return false
}

func indexByteFrom(s string, c byte, from int) int {
	for i := from; i < len(s); i++ {
		if s[i] == c {
			return i
		}
	}
	return -1
}

func containsBytes(h string, needle []byte) bool {
	n := len(needle)
	if n == 0 || n > len(h) {
		return false
	}
	for i := 0; i+n <= len(h); i++ {
		if cmpBytesString(needle, h[i:i+n]) == 0 {
			return true
		}
	}
	return false
}

func searchTable(t strTable, key string) bool {
	lo, hi := 0, t.count
	for lo < hi {
		mid := int(uint(lo+hi) >> 1)
		if cmpBytesString(t.at(mid), key) < 0 {
			lo = mid + 1
		} else {
			hi = mid
		}
	}
	return lo < t.count && cmpBytesString(t.at(lo), key) == 0
}

func cmpBytesString(a []byte, b string) int {
	n := min(len(a), len(b))
	for i := range n {
		if a[i] != b[i] {
			if a[i] < b[i] {
				return -1
			}
			return 1
		}
	}
	switch {
	case len(a) < len(b):
		return -1
	case len(a) > len(b):
		return 1
	}
	return 0
}

func normalize(host string) (string, bool) {
	for len(host) > 0 && host[len(host)-1] == '.' {
		host = host[:len(host)-1]
	}
	if host == "" {
		return "", false
	}
	upper := false
	for i := range len(host) {
		if c := host[i]; c >= 'A' && c <= 'Z' {
			upper = true
			break
		}
	}
	if !upper {
		return host, true
	}
	b := make([]byte, len(host))
	for i := range len(host) {
		c := host[i]
		if c >= 'A' && c <= 'Z' {
			c += 'a' - 'A'
		}
		b[i] = c
	}
	return string(b), true
}

func Normalize(host string) (string, bool) { return normalize(host) }
