package h2chrome

import (
	"strconv"
	"strings"

	"golang.org/x/net/http2"
)

// Everything a passive observer can see about an HTTP/2 client before it has
// sent a single byte of anything meaningful: which settings, in which order,
// with which values, how much connection window it opens with, whether it sends
// PRIORITY frames, and in which order it lays out the pseudo-headers.
//
// The Go standard library hard-codes every one of those, which is why this
// package exists. It does not re-implement HTTP/2: framing and HPACK come from
// golang.org/x/net/http2 and its hpack subpackage, both exported. Only the
// decisions that make up the fingerprint are ours.
type Profile struct {
	Settings          []http2.Setting
	ConnectionWindow  uint32
	MaxFrameSize      uint32
	HeaderTableSize   uint32
	InitialWindowSize uint32
	MaxHeaderListSize uint32
	PseudoOrder       []string
	HeaderOrder       []string
	Priority          *Priority
}

// Priority is what a client that still speaks RFC 7540 priorities would put in
// its HEADERS frame. Chrome stopped in M110 and switched to the `priority`
// request header, so the current profile leaves this nil and the third field of
// the Akamai fingerprint stays "0".
type Priority struct {
	StreamDep uint32
	Exclusive bool
	Weight    uint8
}

const (
	settingHeaderTableSize   = http2.SettingHeaderTableSize
	settingEnablePush        = http2.SettingEnablePush
	settingInitialWindowSize = http2.SettingInitialWindowSize
	settingMaxHeaderListSize = http2.SettingMaxHeaderListSize
)

// Chrome131 is `1:65536;2:0;4:6291456;6:262144|15663105|0|m,a,s,p`.
var Chrome131 = Profile{
	Settings: []http2.Setting{
		{ID: settingHeaderTableSize, Val: 65536},
		{ID: settingEnablePush, Val: 0},
		{ID: settingInitialWindowSize, Val: 6291456},
		{ID: settingMaxHeaderListSize, Val: 262144},
	},
	ConnectionWindow:  15663105,
	MaxFrameSize:      16384,
	HeaderTableSize:   65536,
	InitialWindowSize: 6291456,
	MaxHeaderListSize: 262144,
	PseudoOrder:       []string{":method", ":authority", ":scheme", ":path"},
	HeaderOrder: []string{
		"content-length",
		"sec-ch-ua",
		"content-type",
		"sec-ch-ua-mobile",
		"user-agent",
		"sec-ch-ua-platform",
		"accept",
		"origin",
		"sec-fetch-site",
		"sec-fetch-mode",
		"sec-fetch-dest",
		"referer",
		"accept-encoding",
		"accept-language",
		"priority",
	},
}

func (p Profile) setting(id http2.SettingID) (uint32, bool) {
	for _, s := range p.Settings {
		if s.ID == id {
			return s.Val, true
		}
	}
	return 0, false
}

// Fingerprint renders the profile the way the services that recognise clients
// render it, so a mismatch between what we think we look like and what a check
// site reports is one string comparison away.
func (p Profile) Fingerprint() string {
	var b strings.Builder
	for i, s := range p.Settings {
		if i > 0 {
			b.WriteByte(';')
		}
		b.WriteString(strconv.FormatUint(uint64(s.ID), 10))
		b.WriteByte(':')
		b.WriteString(strconv.FormatUint(uint64(s.Val), 10))
	}
	b.WriteByte('|')
	b.WriteString(strconv.FormatUint(uint64(p.ConnectionWindow), 10))
	b.WriteByte('|')
	if p.Priority == nil {
		b.WriteByte('0')
	} else {
		exclusive := "0"
		if p.Priority.Exclusive {
			exclusive = "1"
		}
		b.WriteString("1:" + exclusive + ":" +
			strconv.FormatUint(uint64(p.Priority.StreamDep), 10) + ":" +
			strconv.FormatUint(uint64(p.Priority.Weight)+1, 10))
	}
	b.WriteByte('|')
	for i, name := range p.PseudoOrder {
		if i > 0 {
			b.WriteByte(',')
		}
		b.WriteString(name[1:2])
	}
	return b.String()
}
