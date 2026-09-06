package main

import (
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
		ListenUDP: func(_ interface {
			Deadline() (time.Time, bool)
			Done() <-chan struct{}
			Err() error
			Value(any) any
		}) (net.PacketConn, error) {
			return net.ListenPacket("udp", ":0")
		},
	})
	defer wire.Close()

	client := wire.Client()
	client.Timeout = *timeout

	req, err := http.NewRequest(http.MethodGet, *target, nil)
	if err != nil {
		log.Fatalf("request: %v", err)
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

	body, _ := io.ReadAll(io.LimitReader(resp.Body, 64<<10))
	fmt.Printf("over: %s, status %d\n\n%s\n", wire.Protocol(), resp.StatusCode, body)
}
