package usp

import (
	"bufio"
	"encoding/binary"
	"errors"
	"fmt"
	"io"
	"math/rand/v2"
)

const (
	Version = 1

	HeaderSize = 8
	MaxPayload = 1 << 20

	DefaultStreamWindow  = 512 << 10
	DefaultSessionWindow = 12 << 20
	DefaultChunk         = 32 << 10

	MaxPadding = 255
)

type Type uint8

const (
	TypeHelloAck Type = 0x01
	TypeOpen     Type = 0x02
	TypeOpenOK   Type = 0x03
	TypeOpenErr  Type = 0x04
	TypeData     Type = 0x05
	TypeEOF      Type = 0x06
	TypeReset    Type = 0x07
	TypeWindow   Type = 0x08
	TypeDgram    Type = 0x09
	TypePing     Type = 0x0A
	TypePong     Type = 0x0B
	TypeSettings Type = 0x0C
	TypeGoaway   Type = 0x0D
	TypeStats    Type = 0x0E
	TypeAck      Type = 0x0F
)

var typeNames = [...]string{
	TypeHelloAck: "HELLO_ACK",
	TypeOpen:     "OPEN",
	TypeOpenOK:   "OPEN_OK",
	TypeOpenErr:  "OPEN_ERR",
	TypeData:     "DATA",
	TypeEOF:      "EOF",
	TypeReset:    "RESET",
	TypeWindow:   "WINDOW",
	TypeDgram:    "DGRAM",
	TypePing:     "PING",
	TypePong:     "PONG",
	TypeSettings: "SETTINGS",
	TypeGoaway:   "GOAWAY",
	TypeStats:    "STATS",
	TypeAck:      "ACK",
}

func (t Type) String() string {
	if int(t) < len(typeNames) && typeNames[t] != "" {
		return typeNames[t]
	}
	return fmt.Sprintf("TYPE(0x%02x)", uint8(t))
}

func (t Type) Control() bool {
	switch t {
	case TypeData, TypeDgram:
		return false
	default:
		return true
	}
}

type Flags uint8

const (
	FlagPadded Flags = 1 << 0
	FlagFin    Flags = 1 << 1
	FlagUDP    Flags = 1 << 2
	FlagUrgent Flags = 1 << 3
)

func (f Flags) Has(x Flags) bool { return f&x == x }

type Frame struct {
	Type    Type
	Flags   Flags
	Stream  uint16
	Payload []byte
}

var (
	ErrFrameTooLarge = errors.New("usp: frame exceeds the maximum payload")
	ErrBadPadding    = errors.New("usp: padding does not fit the payload")
	ErrBadFrame      = errors.New("usp: malformed frame")
)

func PutHeader(dst []byte, t Type, fl Flags, stream uint16, length int) {
	dst[0] = byte(t)
	dst[1] = byte(fl)
	binary.BigEndian.PutUint16(dst[2:], stream)
	binary.BigEndian.PutUint32(dst[4:], uint32(length))
}

type Padder interface {
	Pad(t Type, payload int) int
}

type jitterPad struct {
	src   *rand.Rand
	upTo  int
	below int
}

func NewJitterPad(seed uint64, below, upTo int) Padder {
	return &jitterPad{src: rand.New(rand.NewPCG(seed, seed^0x9e3779b97f4a7c15)), below: below, upTo: upTo}
}

func (p *jitterPad) Pad(t Type, payload int) int {
	if p.upTo <= 0 {
		return 0
	}
	switch t {
	case TypeData, TypeDgram:
		if payload >= p.below {
			return 0
		}
	case TypeOpen, TypeOpenOK, TypePing, TypePong:
	default:
		return 0
	}
	return p.src.IntN(min(p.upTo, MaxPadding) + 1)
}

type Writer struct {
	bw     *bufio.Writer
	padder Padder
	tap    func([]byte)
	hdr    [HeaderSize]byte
	pad    [MaxPadding + 2]byte
	out    int64
}

func NewWriter(w io.Writer, size int, padder Padder) *Writer {
	return &Writer{bw: bufio.NewWriterSize(w, size), padder: padder}
}

// SetTap watches the encoded stream before it reaches the buffer. Replay has to
// see every byte a frame turns into, including the ones a broken connection
// never flushed: those are precisely the ones a resumed leg has to send again.
func (w *Writer) SetTap(f func([]byte)) { w.tap = f }

func (w *Writer) Written() int64 { return w.out }

func (w *Writer) Buffered() int { return w.bw.Buffered() }

func (w *Writer) emit(p []byte) error {
	if w.tap != nil {
		w.tap(p)
	}
	_, err := w.bw.Write(p)
	return err
}

func (w *Writer) WriteFrame(f *Frame) error {
	if len(f.Payload) > MaxPayload {
		return ErrFrameTooLarge
	}

	pad := 0
	flags := f.Flags
	if w.padder != nil {
		if pad = w.padder.Pad(f.Type, len(f.Payload)); pad > 0 {
			flags |= FlagPadded
		}
	}

	length := len(f.Payload)
	if pad > 0 {
		length += pad + 2
	}
	if length > MaxPayload {
		pad, length, flags = 0, len(f.Payload), f.Flags
	}

	PutHeader(w.hdr[:], f.Type, flags, f.Stream, length)
	if err := w.emit(w.hdr[:]); err != nil {
		return err
	}
	if len(f.Payload) > 0 {
		if err := w.emit(f.Payload); err != nil {
			return err
		}
	}
	if pad > 0 {
		binary.BigEndian.PutUint16(w.pad[:], uint16(pad))
		if err := w.emit(w.pad[:pad+2]); err != nil {
			return err
		}
	}
	w.out += int64(HeaderSize + length)
	return nil
}

func (w *Writer) Flush() error { return w.bw.Flush() }

type Reader struct {
	br  *bufio.Reader
	hdr [HeaderSize]byte
	in  int64
}

func NewReader(r io.Reader, size int) *Reader {
	return &Reader{br: bufio.NewReaderSize(r, size)}
}

func (r *Reader) Read(n int) ([]byte, error) { return r.br.Peek(n) }

func (r *Reader) Consumed() int64 { return r.in }

func (r *Reader) ReadFrame(into []byte) (Frame, []byte, error) {
	if _, err := io.ReadFull(r.br, r.hdr[:]); err != nil {
		return Frame{}, into, err
	}
	length := int(binary.BigEndian.Uint32(r.hdr[4:]))
	if length > MaxPayload {
		return Frame{}, into, ErrFrameTooLarge
	}

	buf := into
	if cap(buf) < length {
		buf = make([]byte, length)
	}
	buf = buf[:length]
	if length > 0 {
		if _, err := io.ReadFull(r.br, buf); err != nil {
			return Frame{}, buf, err
		}
	}
	r.in += int64(HeaderSize + length)

	f := Frame{
		Type:    Type(r.hdr[0]),
		Flags:   Flags(r.hdr[1]),
		Stream:  binary.BigEndian.Uint16(r.hdr[2:]),
		Payload: buf,
	}
	if f.Flags.Has(FlagPadded) {
		if len(buf) < 2 {
			return Frame{}, buf, ErrBadPadding
		}
		pad := int(binary.BigEndian.Uint16(buf[len(buf)-2:]))
		if pad+2 > len(buf) {
			return Frame{}, buf, ErrBadPadding
		}
		f.Payload = buf[:len(buf)-pad-2]
	}
	return f, buf, nil
}
