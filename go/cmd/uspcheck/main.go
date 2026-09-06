package main

import (
	"context"
	"flag"
	"fmt"
	"io"
	"log"
	"net/http"
	"os"
	"strings"
	"time"

	"github.com/miekg/dns"

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
	dnsName := flag.String("dns", "", "resolve a name over a datagram stream")
	maxRead := flag.Int64("max", 2048, "how many bytes to read back")
	wait := flag.Duration("wait", 8*time.Second, "how long to wait for an answer")
	noise := flag.Int("noise", 0, "pull this many bytes on another stream first, to fill the tunnel")
	state := flag.String("state", "", "keep the session in this directory between runs")
	suspend := flag.Bool("suspend", false, "leave the session behind instead of closing it")
	flag.Parse()

	ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
	defer cancel()

	session, err := edge.Open(ctx, edge.SessionConfig{
		Base:   *base,
		Bearer: *bearer,
		Label:  "uspcheck",
		Edge:   "uspcheck",
		State:  edge.NewStore(*state, 90*time.Second),
		Client: &http.Client{Timeout: 0},
	})
	if err != nil {
		log.Fatalf("open session: %v", err)
	}
	defer func() {
		if *suspend {
			session.Suspend()
			return
		}
		session.Close()
	}()

	opened := time.Now()
	if err := session.Ready(ctx); err != nil {
		log.Fatalf("hello: %v", err)
	}
	hello := session.Hello()
	fmt.Printf("session %s region=%q country=%q streams=%d replay=%dKiB features=%#x resumed=%v greeted in %s\n",
		session.ID(), hello.Region, hello.Country, hello.MaxStreams, hello.ReplayBytes/1024,
		hello.Features, hello.Resumed, time.Since(opened).Round(time.Microsecond))

	rtt, err := session.Mux().Ping(ctx)
	if err != nil {
		log.Fatalf("ping: %v", err)
	}
	fmt.Printf("ping %s\n", rtt.Round(time.Microsecond))

	if *noise > 0 {
		go drain(ctx, session, *noise)
		time.Sleep(400 * time.Millisecond)
	}

	addr, err := usp.ParseAddr(*target)
	if err != nil {
		log.Fatalf("target: %v", err)
	}

	conn, err := session.Mux().OpenStrict(ctx, addr, *udp)
	if err != nil {
		log.Fatalf("open stream to %s: %v", *target, err)
	}
	defer conn.Close()

	if *dnsName != "" {
		query := new(dns.Msg)
		query.SetQuestion(dns.Fqdn(*dnsName), dns.TypeA)
		query.RecursionDesired = true
		raw, err := query.Pack()
		if err != nil {
			log.Fatalf("pack query: %v", err)
		}
		if _, err := conn.Write(raw); err != nil {
			log.Fatalf("write query: %v", err)
		}
		_ = conn.SetReadDeadline(time.Now().Add(*wait))
		buf := make([]byte, 1500)
		n, err := conn.Read(buf)
		if err != nil {
			log.Fatalf("read answer: %v", err)
		}
		answer := new(dns.Msg)
		if err := answer.Unpack(buf[:n]); err != nil {
			log.Fatalf("unpack answer: %v", err)
		}
		fmt.Printf("dns answer %d byte(s): %s\n", n, strings.ReplaceAll(answer.String(), "\n", " | "))
		return
	}

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
	started := time.Now()

	first := make([]byte, 1)
	n, err := conn.Read(first)
	ttfb := time.Since(started)
	if n == 0 && err != nil {
		log.Fatalf("read: %v", err)
	}

	rest, err := io.ReadAll(io.LimitReader(conn, *maxRead-1))
	body := append(first[:n], rest...)
	spent := time.Since(started)
	fmt.Printf("read %d byte(s) in %s, first byte after %s (%.1f Mbit/s)\n",
		len(body), spent.Round(time.Millisecond), ttfb.Round(time.Microsecond),
		float64(len(body)*8)/spent.Seconds()/1e6)
	if len(body) > 0 {
		fmt.Printf("%s\n", firstLines(body, 6))
	}
	if err != nil {
		fmt.Printf("stream ended: %v\n", err)
	}
}

// drain fills the tunnel with a download so the request being measured has
// something to be stuck behind.
func drain(ctx context.Context, session *edge.Session, bytes int) {
	addr, err := usp.ParseAddr("speed.cloudflare.com:80")
	if err != nil {
		return
	}
	conn, err := session.Mux().OpenStrict(ctx, addr, false)
	if err != nil {
		return
	}
	defer conn.Close()

	fmt.Fprintf(conn, "GET /__down?bytes=%d HTTP/1.1\r\nHost: speed.cloudflare.com\r\n"+
		"User-Agent: uspcheck\r\nConnection: close\r\n\r\n", bytes)
	_, _ = io.Copy(io.Discard, conn)
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
