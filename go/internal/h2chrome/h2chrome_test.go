package h2chrome

import (
	"bytes"
	"net/http"
	"slices"
	"strings"
	"testing"

	"golang.org/x/net/http2/hpack"
)

func TestChromeFingerprintIsTheOneServicesReport(t *testing.T) {
	const want = "1:65536;2:0;4:6291456;6:262144|15663105|0|m,a,s,p"
	if got := Chrome131.Fingerprint(); got != want {
		t.Fatalf("fingerprint is\n  %s\nwant\n  %s", got, want)
	}
}

func TestSettingsKeepTheirOrder(t *testing.T) {
	ids := make([]uint16, 0, len(Chrome131.Settings))
	for _, s := range Chrome131.Settings {
		ids = append(ids, uint16(s.ID))
	}
	if !slices.Equal(ids, []uint16{1, 2, 4, 6}) {
		t.Fatalf("settings order is %v", ids)
	}
}

func decode(t *testing.T, block []byte) []hpack.HeaderField {
	t.Helper()
	var out []hpack.HeaderField
	dec := hpack.NewDecoder(Chrome131.HeaderTableSize, func(f hpack.HeaderField) {
		out = append(out, f)
	})
	if _, err := dec.Write(block); err != nil {
		t.Fatalf("hpack: %v", err)
	}
	return out
}

func TestPseudoHeadersComeInChromeOrder(t *testing.T) {
	req, _ := http.NewRequest(http.MethodGet, "https://example.com/a/b?c=d", nil)

	var buf bytes.Buffer
	if err := Chrome131.encode(hpack.NewEncoder(&buf), req, -1); err != nil {
		t.Fatalf("encode: %v", err)
	}

	fields := decode(t, buf.Bytes())
	got := make([]string, 0, 4)
	for _, f := range fields {
		if strings.HasPrefix(f.Name, ":") {
			got = append(got, f.Name)
		}
	}
	want := []string{":method", ":authority", ":scheme", ":path"}
	if !slices.Equal(got, want) {
		t.Fatalf("pseudo-header order is %v, want %v", got, want)
	}
	for _, f := range fields {
		if f.Name == ":path" && f.Value != "/a/b?c=d" {
			t.Fatalf(":path is %q", f.Value)
		}
		if f.Name == ":authority" && f.Value != "example.com" {
			t.Fatalf(":authority is %q", f.Value)
		}
	}
}

func TestHeaderOrderFollowsTheProfileThenSorts(t *testing.T) {
	req, _ := http.NewRequest(http.MethodGet, "https://example.com/", nil)
	for name, value := range map[string]string{
		"accept-language": "en-US,en;q=0.9",
		"user-agent":      "chrome",
		"sec-ch-ua":       `"Chromium";v="131"`,
		"accept":          "*/*",
		"zzz-custom":      "1",
		"aaa-custom":      "2",
		"accept-encoding": "gzip, deflate, br, zstd",
	} {
		req.Header.Set(name, value)
	}

	var buf bytes.Buffer
	if err := Chrome131.encode(hpack.NewEncoder(&buf), req, -1); err != nil {
		t.Fatalf("encode: %v", err)
	}

	got := make([]string, 0, 8)
	for _, f := range decode(t, buf.Bytes()) {
		if !strings.HasPrefix(f.Name, ":") {
			got = append(got, f.Name)
		}
	}
	want := []string{
		"sec-ch-ua", "user-agent", "accept",
		"accept-encoding", "accept-language",
		"aaa-custom", "zzz-custom",
	}
	if !slices.Equal(got, want) {
		t.Fatalf("header order is %v, want %v", got, want)
	}
}

func TestHopByHopHeadersNeverReachTheWire(t *testing.T) {
	req, _ := http.NewRequest(http.MethodGet, "https://example.com/", nil)
	req.Header.Set("Connection", "keep-alive")
	req.Header.Set("Transfer-Encoding", "chunked")
	req.Header.Set("Host", "elsewhere.example")

	var buf bytes.Buffer
	if err := Chrome131.encode(hpack.NewEncoder(&buf), req, -1); err != nil {
		t.Fatalf("encode: %v", err)
	}
	for _, f := range decode(t, buf.Bytes()) {
		if forbidden[f.Name] {
			t.Fatalf("%q was sent over HTTP/2", f.Name)
		}
	}
}

func TestContentLengthIsSentOnlyWithABody(t *testing.T) {
	body := strings.NewReader("hello")
	req, _ := http.NewRequest(http.MethodPost, "https://example.com/", body)

	var buf bytes.Buffer
	if err := Chrome131.encode(hpack.NewEncoder(&buf), req, 5); err != nil {
		t.Fatalf("encode: %v", err)
	}
	found := ""
	for _, f := range decode(t, buf.Bytes()) {
		if f.Name == "content-length" {
			found = f.Value
		}
	}
	if found != "5" {
		t.Fatalf("content-length is %q", found)
	}

	empty, _ := http.NewRequest(http.MethodGet, "https://example.com/", nil)
	buf.Reset()
	if err := Chrome131.encode(hpack.NewEncoder(&buf), empty, -1); err != nil {
		t.Fatalf("encode: %v", err)
	}
	for _, f := range decode(t, buf.Bytes()) {
		if f.Name == "content-length" {
			t.Fatal("a bodyless request carried content-length")
		}
	}
}

func TestOrderMatchesWhatIsActuallyEncoded(t *testing.T) {
	req, _ := http.NewRequest(http.MethodGet, "https://example.com/", nil)
	req.Header.Set("user-agent", "chrome")
	req.Header.Set("accept", "*/*")
	req.Header.Set("x-extra", "1")

	var buf bytes.Buffer
	if err := Chrome131.encode(hpack.NewEncoder(&buf), req, -1); err != nil {
		t.Fatalf("encode: %v", err)
	}
	encoded := make([]string, 0, 8)
	for _, f := range decode(t, buf.Bytes()) {
		encoded = append(encoded, f.Name)
	}
	if !slices.Equal(encoded, Chrome131.Order(req)) {
		t.Fatalf("Order() says %v, the wire says %v", Chrome131.Order(req), encoded)
	}
}
