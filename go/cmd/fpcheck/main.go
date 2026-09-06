package main

import (
	"context"
	"flag"
	"fmt"
	"io"
	"log"
	"net"
	"net/http"
	"net/url"
	"os"
	"time"

	"unsafie/internal/chrome"
	"unsafie/internal/logging"
)

// What a fingerprinting service sees when the client talks to it. The point of
// the whole chrome package is that the answer here matches the answer for the
// browser it claims to be, so it is worth being able to ask.
func main() {
	log.SetFlags(0)
	logging.SetDefault(logging.NewWriter(os.Stderr))

	target := flag.String("url", "https://tls.peet.ws/api/all", "a service that reports what it sees")
	h3 := flag.Bool("h3", false, "let the wire negotiate HTTP/3 first")
	timeout := flag.Duration("timeout", 20*time.Second, "how long to wait")
	stream := flag.Int("stream", 0, "POST this many bytes as a body of unknown length")
	flag.Parse()

	parsed, err := url.Parse(*target)
	if err != nil {
		log.Fatalf("url: %v", err)
	}
	port := parsed.Port()
	if port == "" {
		port = "443"
	}

	fmt.Printf("claiming: %s\n", chrome.Chrome131.Fingerprint())

	wire := chrome.NewWire(chrome.Options{
		Profile:  chrome.Chrome131,
		Host:     parsed.Hostname(),
		Port:     port,
		EnableH3: *h3,
		ListenUDP: func(context.Context) (net.PacketConn, error) {
			return net.ListenPacket("udp", ":0")
		},
	})
	defer wire.Close()

	client := wire.Client()
	client.Timeout = *timeout

	method, body := http.MethodGet, io.Reader(nil)
	if *stream > 0 {
		method = http.MethodPost
		body = &trickle{left: *stream, gap: 20 * time.Millisecond}
	}

	req, err := http.NewRequest(method, *target, body)
	if err != nil {
		log.Fatalf("request: %v", err)
	}
	if *stream > 0 {
		req.ContentLength = -1
		req.Header.Set("content-type", "application/octet-stream")
	}
	req.Header.Set("sec-fetch-dest", "document")
	req.Header.Set("sec-fetch-mode", "navigate")
	req.Header.Set("accept",
		"text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,"+
			"image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7")

	resp, err := client.Do(req)
	if err != nil {
		log.Fatalf("get: %v", err)
	}
	defer resp.Body.Close()

	answer, _ := io.ReadAll(io.LimitReader(resp.Body, 64<<10))
	fmt.Printf("over: %s, status %d\n\n%s\n", wire.Protocol(), resp.StatusCode, answer)
}

// trickle is a request body that never says how long it is and arrives in
// pieces, which is the shape the tunnel's uplink has and the one an HTTP/2
// client is most likely to get wrong.
type trickle struct {
	left int
	gap  time.Duration
}

func (t *trickle) Read(p []byte) (int, error) {
	if t.left <= 0 {
		return 0, io.EOF
	}
	time.Sleep(t.gap)
	n := min(len(p), t.left, 4096)
	for i := range n {
		p[i] = byte('a' + i%26)
	}
	t.left -= n
	return n, nil
}
