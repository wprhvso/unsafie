package rules

import (
	"bytes"
	"encoding/binary"
	"errors"
	"fmt"
	"sort"
	"strings"
)

func checkRule(item string) error {
	if item == "" {
		return errors.New("rules: empty rule")
	}
	if item != strings.ToLower(item) {
		return fmt.Errorf("rules: %q is not lowercase and could never match", item)
	}
	if strings.HasPrefix(item, ".") || strings.HasSuffix(item, ".") {
		return fmt.Errorf("rules: %q has a leading or trailing dot", item)
	}
	return nil
}

type BuildInput struct {
	IPv4      [][2]uint32
	IPv6      [][2][16]byte
	Suffix    []string
	Exact     []string
	Keyword   []string
	Generated int64
	Hash      [32]byte
}

func Build(in BuildInput) ([]byte, error) {
	for i, r := range in.IPv4 {
		if r[0] > r[1] {
			return nil, fmt.Errorf("rules: ipv4 range %d starts after it ends", i)
		}
	}
	for i := 1; i < len(in.IPv4); i++ {
		if in.IPv4[i][0] <= in.IPv4[i-1][1] {
			return nil, errors.New("rules: ipv4 ranges overlap or unsorted")
		}
	}
	for i, r := range in.IPv6 {
		if bytes.Compare(r[0][:], r[1][:]) > 0 {
			return nil, fmt.Errorf("rules: ipv6 range %d starts after it ends", i)
		}
	}
	for i := 1; i < len(in.IPv6); i++ {
		if bytes.Compare(in.IPv6[i][0][:], in.IPv6[i-1][1][:]) <= 0 {
			return nil, errors.New("rules: ipv6 ranges overlap or unsorted")
		}
	}
	if !sort.StringsAreSorted(in.Suffix) {
		return nil, errors.New("rules: suffix table unsorted")
	}
	if !sort.StringsAreSorted(in.Exact) {
		return nil, errors.New("rules: exact table unsorted")
	}
	for _, group := range [][]string{in.Suffix, in.Exact, in.Keyword} {
		for _, item := range group {
			if err := checkRule(item); err != nil {
				return nil, err
			}
		}
	}

	var body bytes.Buffer
	header := make([]byte, HeaderSize)
	copy(header[offMagic:], Magic)
	order.PutUint32(header[offVersion:], Version)
	order.PutUint64(header[offGenerated:], uint64(in.Generated))
	copy(header[offHash:], in.Hash[:])

	put := func(off, v int) { order.PutUint32(header[off:], uint32(v)) }

	put(offIPv4Off, HeaderSize+body.Len())
	put(offIPv4Count, len(in.IPv4))
	for _, r := range in.IPv4 {
		var rec [IPv4RecordSize]byte
		order.PutUint32(rec[0:], r[0])
		order.PutUint32(rec[4:], r[1])
		body.Write(rec[:])
	}

	put(offIPv6Off, HeaderSize+body.Len())
	put(offIPv6Count, len(in.IPv6))
	for _, r := range in.IPv6 {
		body.Write(r[0][:])
		body.Write(r[1][:])
	}

	writeTable := func(items []string, tableOff, countOff, blobOff, blobLenOff int) {
		put(tableOff, HeaderSize+body.Len())
		put(countOff, len(items))
		var blob bytes.Buffer
		off := make([]byte, 4)
		pos := uint32(0)
		for _, it := range items {
			binary.LittleEndian.PutUint32(off, pos)
			body.Write(off)
			blob.WriteString(it)
			pos += uint32(len(it))
		}
		binary.LittleEndian.PutUint32(off, pos)
		body.Write(off)

		put(blobOff, HeaderSize+body.Len())
		put(blobLenOff, blob.Len())
		body.Write(blob.Bytes())
	}

	writeTable(in.Suffix, offSufTable, offSufCount, offSufBlob, offSufBlobLen)
	writeTable(in.Exact, offExcTable, offExcCount, offExcBlob, offExcBlobLen)
	writeTable(in.Keyword, offKwTable, offKwCount, offKwBlob, offKwBlobLen)

	out := make([]byte, 0, HeaderSize+body.Len())
	out = append(out, header...)
	out = append(out, body.Bytes()...)
	return out, nil
}

func (s *Set) DumpIPv6() [][2][16]byte {
	out := make([][2][16]byte, 0, s.ipv6N)
	for i := range s.ipv6N {
		rec := s.ipv6[i*IPv6RecordSize : (i+1)*IPv6RecordSize]
		var pair [2][16]byte
		copy(pair[0][:], rec[:16])
		copy(pair[1][:], rec[16:])
		out = append(out, pair)
	}
	return out
}

func (s *Set) Dump() ([][2]uint32, []string, []string, []string) {
	ranges := make([][2]uint32, 0, s.ipv4N)
	for i := range s.ipv4N {
		rec := s.ipv4[i*IPv4RecordSize:]
		ranges = append(ranges, [2]uint32{order.Uint32(rec), order.Uint32(rec[4:])})
	}
	strs := func(t strTable) []string {
		out := make([]string, 0, t.count)
		for i := range t.count {
			out = append(out, string(t.at(i)))
		}
		return out
	}
	return ranges, strs(s.suffix), strs(s.exact), strs(s.keyword)
}
