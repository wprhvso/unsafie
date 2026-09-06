package chrome

import (
	"strings"

	utls "github.com/refraction-networking/utls"
)

// One build of one browser, pinned.
//
// Pinned rather than randomised on purpose. A client that rolls a different
// fingerprint every launch is unique in the only way that matters — nobody else
// looks like that twice — while a client that looks exactly like the Chrome on
// the desktop next to it is indistinguishable from the most common thing on the
// network. The version is bumped deliberately, in a commit, the way the browser
// itself would.
type Profile struct {
	Name            string
	Version         string
	Major           string
	Platform        string
	PlatformVersion string
	UserAgent       string
	AcceptLanguage  string
	Hello           utls.ClientHelloID
	ALPN            []string

	HeaderTableSize   uint32
	EnablePush        uint32
	InitialWindowSize uint32
	MaxHeaderListSize uint32
	MaxFrameSize      uint32
	ConnectionWindow  uint32
	MaxConcurrent     uint32

	QUICMaxIdleMS       uint32
	QUICMaxDatagramSize uint16
	QUICStreamWindow    uint64
	QUICConnWindow      uint64
	QUICMaxStreams      int64
}

// Chrome131 is what this build claims to be. The HTTP/2 numbers are Chrome's
// own SETTINGS, in the order Chrome sends them; the QUIC numbers are the
// transport parameters Chrome offers on a fresh connection.
var Chrome131 = Profile{
	Name:            "Chrome",
	Version:         "131.0.6778.86",
	Major:           "131",
	Platform:        "Windows",
	PlatformVersion: "10.0.0",
	UserAgent: "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) " +
		"Chrome/131.0.0.0 Safari/537.36",
	AcceptLanguage: "en-US,en;q=0.9",
	Hello:          utls.HelloChrome_120,
	ALPN:           []string{"h2", "http/1.1"},

	HeaderTableSize:   65536,
	EnablePush:        0,
	InitialWindowSize: 6291456,
	MaxHeaderListSize: 262144,
	MaxFrameSize:      16384,
	ConnectionWindow:  15663105,
	MaxConcurrent:     1000,

	QUICMaxIdleMS:       30000,
	QUICMaxDatagramSize: 1350,
	QUICStreamWindow:    6 << 20,
	QUICConnWindow:      15 << 20,
	QUICMaxStreams:      100,
}

func (p Profile) SecCHUA() string {
	return `"Google Chrome";v="` + p.Major + `", "Chromium";v="` + p.Major + `", "Not_A Brand";v="24"`
}

func (p Profile) SecCHUAPlatform() string { return `"` + p.Platform + `"` }

// Fingerprint is what this build would be recognised by, in the shorthand the
// people who do the recognising use. Printed at startup so a mismatch between
// what we think we look like and what a check site reports is one grep away.
func (p Profile) Fingerprint() string {
	var b strings.Builder
	b.WriteString(p.Name)
	b.WriteByte('/')
	b.WriteString(p.Version)
	b.WriteString(" tls=")
	b.WriteString(p.Hello.Client)
	b.WriteByte('-')
	b.WriteString(p.Hello.Version)
	b.WriteString(" h2=1:")
	b.WriteString(utoa(p.HeaderTableSize))
	b.WriteString(";2:")
	b.WriteString(utoa(p.EnablePush))
	b.WriteString(";4:")
	b.WriteString(utoa(p.InitialWindowSize))
	b.WriteString(";6:")
	b.WriteString(utoa(p.MaxHeaderListSize))
	b.WriteByte('|')
	b.WriteString(utoa(p.ConnectionWindow))
	b.WriteString("|0|m,a,s,p")
	return b.String()
}

func utoa(v uint32) string {
	if v == 0 {
		return "0"
	}
	var buf [10]byte
	i := len(buf)
	for v > 0 {
		i--
		buf[i] = byte('0' + v%10)
		v /= 10
	}
	return string(buf[i:])
}
