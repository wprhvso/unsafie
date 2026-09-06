package chrome

import (
	"net/http"
	"strconv"
	"strings"
	"time"
)

// decorator makes every request look like something a browser would send.
//
// Accept-Encoding says gzip even though the payload is an encrypted byte
// stream that will not compress: a browser always says it, and the edge is
// configured never to act on it for this path. Saying "identity" instead would
// be one field that no Chrome on earth sends.
type decorator struct {
	next    http.RoundTripper
	profile Profile
	origin  string
}

func (d *decorator) RoundTrip(req *http.Request) (*http.Response, error) {
	h := req.Header
	set := func(k, v string) {
		if h.Get(k) == "" {
			h.Set(k, v)
		}
	}

	set("sec-ch-ua", d.profile.SecCHUA())
	set("sec-ch-ua-mobile", "?0")
	set("sec-ch-ua-platform", d.profile.SecCHUAPlatform())
	set("upgrade-insecure-requests", "1")
	set("user-agent", d.profile.UserAgent)
	set("accept", "*/*")
	set("origin", d.origin)
	set("sec-fetch-site", "same-origin")
	set("sec-fetch-mode", "cors")
	set("sec-fetch-dest", "empty")
	set("referer", d.origin+"/")
	set("accept-encoding", "gzip, deflate, br, zstd")
	set("accept-language", d.profile.AcceptLanguage)
	set("priority", "u=1, i")

	return d.next.RoundTrip(req)
}

// altSvc reads the one header that decides whether a browser will ever try
// QUIC to a host. Chrome does not guess: it uses HTTP/3 because the origin said
// it could, and it stops when that turns out to have been optimistic.
type altSvc struct {
	h3   bool
	port string
	ttl  time.Duration
}

func parseAltSvc(value string) (altSvc, bool) {
	if value == "" || strings.EqualFold(strings.TrimSpace(value), "clear") {
		return altSvc{}, false
	}

	out := altSvc{ttl: 24 * time.Hour}
	found := false

	for entry := range strings.SplitSeq(value, ",") {
		parts := strings.Split(strings.TrimSpace(entry), ";")
		if len(parts) == 0 {
			continue
		}
		proto, authority, ok := strings.Cut(strings.TrimSpace(parts[0]), "=")
		if !ok {
			continue
		}
		if !strings.HasPrefix(strings.TrimSpace(proto), "h3") {
			continue
		}
		found = true
		out.h3 = true
		authority = strings.Trim(strings.TrimSpace(authority), `"`)
		if _, port, ok := strings.Cut(authority, ":"); ok && port != "" {
			out.port = port
		}
		for _, param := range parts[1:] {
			key, val, ok := strings.Cut(strings.TrimSpace(param), "=")
			if !ok || strings.TrimSpace(key) != "ma" {
				continue
			}
			if secs, err := strconv.Atoi(strings.Trim(strings.TrimSpace(val), `"`)); err == nil && secs > 0 {
				out.ttl = time.Duration(secs) * time.Second
			}
		}
	}
	return out, found
}
