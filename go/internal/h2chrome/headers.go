package h2chrome

import (
	"net/http"
	"slices"
	"sort"
	"strconv"
	"strings"

	"golang.org/x/net/http2/hpack"
)

var errBadHeader = &protocolError{"h2chrome: header cannot be sent over HTTP/2"}

type protocolError struct{ msg string }

func (e *protocolError) Error() string { return e.msg }

// Hop by hop headers have no meaning in HTTP/2 and a peer is entitled to reject
// a request carrying them.
var forbidden = map[string]bool{
	"connection":        true,
	"proxy-connection":  true,
	"keep-alive":        true,
	"transfer-encoding": true,
	"upgrade":           true,
	"host":              true,
}

// encode lays a request out in Chrome's order. Everything the profile names
// comes first, in that exact sequence; anything else follows sorted, so two
// requests carrying the same unusual header never disagree about where it goes.
func (p Profile) encode(enc *hpack.Encoder, req *http.Request, contentLength int64) error {
	path := req.URL.RequestURI()
	if path == "" {
		path = "/"
	}
	scheme := req.URL.Scheme
	if scheme == "" {
		scheme = "https"
	}
	authority := req.Host
	if authority == "" {
		authority = req.URL.Host
	}

	pseudo := map[string]string{
		":method":    req.Method,
		":authority": authority,
		":scheme":    scheme,
		":path":      path,
	}
	for _, name := range p.PseudoOrder {
		value, ok := pseudo[name]
		if !ok {
			continue
		}
		if err := enc.WriteField(hpack.HeaderField{Name: name, Value: value}); err != nil {
			return err
		}
	}

	values := make(map[string][]string, len(req.Header)+1)
	for name, list := range req.Header {
		lower := strings.ToLower(name)
		if forbidden[lower] {
			continue
		}
		if strings.ContainsAny(lower, " \t\r\n\x00") {
			return errBadHeader
		}
		values[lower] = append(values[lower], list...)
	}
	if contentLength >= 0 && req.Body != nil {
		values["content-length"] = []string{strconv.FormatInt(contentLength, 10)}
	}

	write := func(name string) error {
		for _, value := range values[name] {
			if err := enc.WriteField(hpack.HeaderField{Name: name, Value: value}); err != nil {
				return err
			}
		}
		delete(values, name)
		return nil
	}

	for _, name := range p.HeaderOrder {
		if err := write(name); err != nil {
			return err
		}
	}

	rest := make([]string, 0, len(values))
	for name := range values {
		rest = append(rest, name)
	}
	sort.Strings(rest)
	for _, name := range rest {
		if err := write(name); err != nil {
			return err
		}
	}
	return nil
}

// Order is what the profile would emit for a request, without emitting it.
// Tests and the fingerprint endpoint both want to see it.
func (p Profile) Order(req *http.Request) []string {
	out := slices.Clone(p.PseudoOrder)
	seen := map[string]bool{}
	for name := range req.Header {
		seen[strings.ToLower(name)] = true
	}
	for _, name := range p.HeaderOrder {
		if seen[name] {
			out = append(out, name)
			delete(seen, name)
		}
	}
	rest := make([]string, 0, len(seen))
	for name := range seen {
		if !forbidden[name] {
			rest = append(rest, name)
		}
	}
	sort.Strings(rest)
	return append(out, rest...)
}
