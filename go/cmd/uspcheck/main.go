package main

import (
	"context"
	"flag"
	"fmt"
	"io"
	"log"
	"net/http"
	"os"
	"time"

	"unsafie/internal/edge"
	"unsafie/internal/logging"
	"unsafie/internal/netx"
	"unsafie/internal/usp"
)

func main() {
	log.SetFlags(0)
	logging.SetDefault(logging.NewWriter(os.Stderr))

	base := flag.String("base", "http://127.0.0.1:8091", "edge base URL, with or without TLS")
	bearer := flag.String("bearer", "", "bearer token nginx expects")
	target := flag.String("target", "example.com:80", "what to reach through the tunnel")
	request := flag.String("request", "", "raw bytes to send once the stream is open")
	udp := flag.Bool("udp", false, "open a datagram stream instead of a byte stream")
	wait := flag.Duration("wait", 8*time.Second, "how long to wait for an answer")
	flag.Parse()

	ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
	defer cancel()

	session, err := edge.Open(ctx, edge.SessionConfig{
		Base:   *base,
		Bearer: *bearer,
		Label:  "uspcheck",
		Client: &http.Client{Timeout: 0},
	})
	if err != nil {
		log.Fatalf("open session: %v", err)
	}
	defer session.Close()

	hello := session.Hello()
	fmt.Printf("session %s region=%q country=%q streams=%d replay=%dKiB features=%#x\n",
		session.ID(), hello.Region, hello.Country, hello.MaxStreams, hello.ReplayBytes/1024, hello.Features)

	rtt, err := session.Mux().Ping(ctx)
	if err != nil {
		log.Fatalf("ping: %v", err)
	}
	fmt.Printf("ping %s\n", rtt.Round(time.Microsecond))

	addr, err := usp.ParseAddr(*target)
	if err != nil {
		log.Fatalf("target: %v", err)
	}

	conn, err := session.Mux().OpenStrict(ctx, addr, *udp)
	if err != nil {
		log.Fatalf("open stream to %s: %v", *target, err)
	}
	defer conn.Close()

	payload := *request
	if payload == "" && !*udp {
		host, _ := netx.SplitTarget(*target)
		payload = "GET / HTTP/1.1\r\nHost: " + host + "\r\nUser-Agent: uspcheck\r\nConnection: close\r\n\r\n"
	}
	if payload != "" {
		if _, err := io.WriteString(conn, payload); err != nil {
			log.Fatalf("write: %v", err)
		}
	}

	_ = conn.SetReadDeadline(time.Now().Add(*wait))
	body, err := io.ReadAll(io.LimitReader(conn, 2048))
	fmt.Printf("read %d byte(s)\n", len(body))
	if len(body) > 0 {
		fmt.Printf("%s\n", firstLines(body, 6))
	}
	if err != nil {
		fmt.Printf("stream ended: %v\n", err)
	}
}

func firstLines(b []byte, n int) []byte {
	count := 0
	for i, c := range b {
		if c != '\n' {
			continue
		}
		count++
		if count == n {
			return b[:i]
		}
	}
	return b
}
