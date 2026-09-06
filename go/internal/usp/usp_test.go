package usp

import (
	"bytes"
	"net/netip"
	"testing"
)

func TestFrameRoundTripWithPadding(t *testing.T) {
	var out bytes.Buffer
	w := NewWriter(&out, 4096, NewJitterPad(7, 4096, 64))

	payload := []byte("the quick brown fox")
	if err := w.WriteFrame(&Frame{Type: TypeData, Stream: 9, Payload: payload}); err != nil {
		t.Fatalf("write: %v", err)
	}
	if err := w.Flush(); err != nil {
		t.Fatalf("flush: %v", err)
	}

	r := NewReader(&out, 4096)
	got, _, err := r.ReadFrame(nil)
	if err != nil {
		t.Fatalf("read: %v", err)
	}
	if got.Type != TypeData || got.Stream != 9 {
		t.Fatalf("header changed: %+v", got)
	}
	if !bytes.Equal(got.Payload, payload) {
		t.Fatalf("payload changed: %q", got.Payload)
	}
	if w.Written() <= int64(HeaderSize+len(payload)) {
		t.Fatalf("padding was not applied: %d bytes on the wire", w.Written())
	}
}

func TestReaderCountsEveryByteItConsumed(t *testing.T) {
	var out bytes.Buffer
	w := NewWriter(&out, 4096, nil)
	for i := range 4 {
		if err := w.WriteFrame(&Frame{Type: TypePing, Stream: uint16(i), Payload: []byte{1, 2, 3}}); err != nil {
			t.Fatal(err)
		}
	}
	_ = w.Flush()

	r := NewReader(&out, 4096)
	var buf []byte
	for range 4 {
		if _, buf, _ = r.ReadFrame(buf); false {
			t.Fatal("unreachable")
		}
	}
	if r.Consumed() != w.Written() {
		t.Fatalf("offsets disagree: read %d, wrote %d", r.Consumed(), w.Written())
	}
}

func TestAddressRoundTrip(t *testing.T) {
	for _, target := range []string{"1.2.3.4:443", "[2001:db8::1]:53", "example.com:80"} {
		addr, err := ParseAddr(target)
		if err != nil {
			t.Fatalf("%s: %v", target, err)
		}
		back, rest, err := DecodeAddr(AppendAddr(nil, addr))
		if err != nil {
			t.Fatalf("%s: %v", target, err)
		}
		if len(rest) != 0 {
			t.Fatalf("%s: %d trailing byte(s)", target, len(rest))
		}
		if back.String() != addr.String() {
			t.Fatalf("%s became %s", target, back)
		}
	}
}

func TestHelloRoundTrip(t *testing.T) {
	in := ServerHello{
		Version: Version, Session: "abcdefghijklmnopqrstuv",
		StreamWindow: 1 << 19, SessionWindow: 1 << 23,
		Features: FeatureUDP | FeatureResume,
		Region:   "waw", Country: "PL", ASN: 64500,
		ExitIP: netip.MustParseAddr("203.0.113.7"), KeepaliveMS: 15000,
		MaxStreams: 4096, ReplayBytes: 1 << 22, Resumed: true,
	}
	out, err := DecodeServerHello(in.Encode())
	if err != nil {
		t.Fatalf("decode: %v", err)
	}
	if out.Session != in.Session || out.Country != in.Country || out.ASN != in.ASN || !out.Resumed {
		t.Fatalf("hello changed: %+v", out)
	}
	if out.ExitIP != in.ExitIP {
		t.Fatalf("exit address changed: %s", out.ExitIP)
	}
}

func TestReasonsBlameTheRightParty(t *testing.T) {
	cases := map[Reason]Fault{
		ReasonRefused:         FaultService,
		ReasonPeerReset:       FaultService,
		ReasonTimeout:         FaultExit,
		ReasonDNS:             FaultExit,
		ReasonHandshakeStall:  FaultExit,
		ReasonGeoBlocked:      FaultGeo,
		ReasonPolicy:          FaultGeo,
		ReasonOverloaded:      FaultEdge,
		ReasonUnauthorized:    FaultEdge,
		ReasonSessionGone:     FaultEdge,
		ReasonNone:            FaultNone,
		ReasonHostUnreachable: FaultExit,
	}
	for reason, want := range cases {
		if got := reason.Blames(); got != want {
			t.Fatalf("%s blames %s, want %s", reason, got, want)
		}
	}
	if ReasonRefused.Retryable() {
		t.Fatal("a refused connection is the destination's own answer, retrying elsewhere is pointless")
	}
	if !ReasonTimeout.Retryable() {
		t.Fatal("a timeout is exactly what another exit is for")
	}
}

func TestPaddingCannotOverrunThePayload(t *testing.T) {
	var out bytes.Buffer
	w := NewWriter(&out, 256, nil)
	_ = w.WriteFrame(&Frame{Type: TypeData, Flags: FlagPadded, Stream: 1, Payload: []byte{0xff, 0xff}})
	_ = w.Flush()

	r := NewReader(&out, 256)
	if _, _, err := r.ReadFrame(nil); err == nil {
		t.Fatal("a padding length longer than the frame was accepted")
	}
}
