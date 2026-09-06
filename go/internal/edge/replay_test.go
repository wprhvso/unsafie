package edge

import (
	"bytes"
	"testing"
)

func TestRingReplaysFromAnOffsetItStillHolds(t *testing.T) {
	r := newRing(64)
	r.Append([]byte("0123456789"))
	r.Append([]byte("abcdefghij"))

	got, ok := r.Since(10)
	if !ok {
		t.Fatal("the ring forgot bytes it still had room for")
	}
	if string(got) != "abcdefghij" {
		t.Fatalf("replayed %q", got)
	}
	if r.End() != 20 {
		t.Fatalf("end is %d, want 20", r.End())
	}
}

func TestRingRefusesWhatItHasAlreadyDropped(t *testing.T) {
	r := newRing(16)
	r.Append(bytes.Repeat([]byte("x"), 40))

	if _, ok := r.Since(0); ok {
		t.Fatal("the ring claimed to hold bytes that scrolled out")
	}
	got, ok := r.Since(30)
	if !ok || len(got) != 10 {
		t.Fatalf("replay from a live offset returned %d byte(s), ok=%v", len(got), ok)
	}
}

func TestRingWrapsAcrossTheSeam(t *testing.T) {
	r := newRing(8)
	r.Append([]byte("abcde"))
	r.Append([]byte("fghij"))

	got, ok := r.Since(2)
	if !ok {
		t.Fatal("offset 2 should still be inside an 8 byte ring holding 10 bytes")
	}
	if string(got) != "cdefghij" {
		t.Fatalf("replayed %q across the wrap", got)
	}
}

func TestRecvBufferKeepsDatagramBoundaries(t *testing.T) {
	b := newRecvBuf(true)
	b.push([]byte("first"))
	b.push([]byte("second"))

	out := make([]byte, 32)
	if n := b.pull(out); string(out[:n]) != "first" {
		t.Fatalf("first read returned %q", out[:n])
	}
	if n := b.pull(out); string(out[:n]) != "second" {
		t.Fatalf("second read returned %q", out[:n])
	}
}

func TestRecvBufferConcatenatesStreams(t *testing.T) {
	b := newRecvBuf(false)
	b.push([]byte("abc"))
	b.push([]byte("def"))

	out := make([]byte, 4)
	n := b.pull(out)
	if string(out[:n]) != "abcd" {
		t.Fatalf("stream read returned %q", out[:n])
	}
	n = b.pull(out)
	if string(out[:n]) != "ef" {
		t.Fatalf("second stream read returned %q", out[:n])
	}
}

func TestCreditIsAllOrNothingForDatagrams(t *testing.T) {
	c := newCredit(10)
	if got, ok := c.takeExact(20); !ok || got != 0 {
		t.Fatalf("takeExact gave %d with ok=%v", got, ok)
	}
	if got, _ := c.takeExact(10); got != 10 {
		t.Fatalf("takeExact gave %d, want 10", got)
	}
	if got, _ := c.take(1); got != 0 {
		t.Fatalf("credit was not consumed: %d left", got)
	}
}
