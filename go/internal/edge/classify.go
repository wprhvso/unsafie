package edge

import (
	"context"
	"crypto/tls"
	"errors"
	"io"
	"net"
	"net/http"
	"strings"
	"syscall"

	"unsafie/internal/usp"
)

// Classify turns whatever went wrong on the way to an exit into the two things
// the picker can act on: whose fault it looks like, and what exactly happened.
//
// The distinction that matters is between "this server is unusable" and "this
// server cannot reach that one destination". A 502 from nginx is the first; an
// OPEN_ERR carrying host-unreachable is the second. Everything else in this
// file exists to keep those two from being averaged into one number.
func Classify(err error) (usp.Fault, usp.Reason) {
	if err == nil {
		return usp.FaultNone, usp.ReasonNone
	}

	var open *OpenError
	if errors.As(err, &open) {
		return open.Reason.Blames(), open.Reason
	}

	var status *StatusError
	if errors.As(err, &status) {
		return classifyStatus(status.Status)
	}

	switch {
	case errors.Is(err, context.Canceled):
		return usp.FaultNone, usp.ReasonNone
	case errors.Is(err, context.DeadlineExceeded):
		return usp.FaultEdge, usp.ReasonTimeout
	case errors.Is(err, ErrUnrecoverable), errors.Is(err, ErrSessionGone):
		return usp.FaultEdge, usp.ReasonSessionGone
	case errors.Is(err, usp.ErrVersion), errors.Is(err, usp.ErrBadHello), errors.Is(err, usp.ErrBadFrame):
		return usp.FaultEdge, usp.ReasonProtocol
	}

	var dnsErr *net.DNSError
	if errors.As(err, &dnsErr) {
		return usp.FaultEdge, usp.ReasonDNS
	}

	var certErr *tls.CertificateVerificationError
	if errors.As(err, &certErr) {
		return usp.FaultEdge, usp.ReasonHandshakeStall
	}

	var alert tls.AlertError
	if errors.As(err, &alert) {
		return usp.FaultEdge, usp.ReasonHandshakeStall
	}

	switch {
	case errors.Is(err, syscall.ECONNREFUSED):
		return usp.FaultEdge, usp.ReasonRefused
	case errors.Is(err, syscall.ECONNRESET), errors.Is(err, syscall.EPIPE):
		return usp.FaultEdge, usp.ReasonHandshakeStall
	case errors.Is(err, syscall.EHOSTUNREACH):
		return usp.FaultLocal, usp.ReasonHostUnreachable
	case errors.Is(err, syscall.ENETUNREACH), errors.Is(err, syscall.ENETDOWN):
		return usp.FaultLocal, usp.ReasonNetUnreachable
	}

	var netErr net.Error
	if errors.As(err, &netErr) && netErr.Timeout() {
		return usp.FaultEdge, usp.ReasonTimeout
	}

	if errors.Is(err, io.ErrUnexpectedEOF) || errors.Is(err, io.EOF) {
		return usp.FaultEdge, usp.ReasonHandshakeStall
	}

	// quic-go and the TLS stack both report a good part of their failures as
	// plain strings; matching on them is ugly and still better than throwing a
	// whole class of censorship signals into "unknown".
	text := strings.ToLower(err.Error())
	switch {
	case strings.Contains(text, "handshake"), strings.Contains(text, "no recent network activity"):
		return usp.FaultEdge, usp.ReasonHandshakeStall
	case strings.Contains(text, "timeout"), strings.Contains(text, "deadline"):
		return usp.FaultEdge, usp.ReasonTimeout
	case strings.Contains(text, "refused"):
		return usp.FaultEdge, usp.ReasonRefused
	case strings.Contains(text, "unreachable"):
		return usp.FaultLocal, usp.ReasonNetUnreachable
	case strings.Contains(text, "reset"):
		return usp.FaultEdge, usp.ReasonHandshakeStall
	}
	return usp.FaultEdge, usp.ReasonUnreachableEdge
}

func classifyStatus(code int) (usp.Fault, usp.Reason) {
	switch code {
	case http.StatusUnauthorized, http.StatusForbidden:
		return usp.FaultEdge, usp.ReasonUnauthorized
	case http.StatusNotFound, http.StatusGone, http.StatusConflict:
		return usp.FaultEdge, usp.ReasonSessionGone
	case http.StatusTooManyRequests:
		return usp.FaultEdge, usp.ReasonRateLimited
	case http.StatusBadGateway, http.StatusServiceUnavailable, http.StatusGatewayTimeout:
		return usp.FaultEdge, usp.ReasonOverloaded
	case http.StatusRequestTimeout:
		return usp.FaultEdge, usp.ReasonTimeout
	}
	if code >= 500 {
		return usp.FaultEdge, usp.ReasonInternal
	}
	return usp.FaultEdge, usp.ReasonProtocol
}
