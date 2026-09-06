package usp

import "fmt"

type Reason uint8

const (
	ReasonNone Reason = iota
	ReasonRefused
	ReasonHostUnreachable
	ReasonNetUnreachable
	ReasonTimeout
	ReasonDNS
	ReasonPolicy
	ReasonGeoBlocked
	ReasonRateLimited
	ReasonInternal
	ReasonIdle
	ReasonSessionGone
	ReasonProtocol
	ReasonPeerReset
	ReasonHandshakeStall
	ReasonShutdown
	ReasonOverloaded
	ReasonTooManyStreams
	ReasonUnauthorized
	ReasonUnreachableEdge
)

var reasonNames = [...]string{
	ReasonNone:            "none",
	ReasonRefused:         "refused",
	ReasonHostUnreachable: "host-unreachable",
	ReasonNetUnreachable:  "net-unreachable",
	ReasonTimeout:         "timeout",
	ReasonDNS:             "dns",
	ReasonPolicy:          "policy",
	ReasonGeoBlocked:      "geo-blocked",
	ReasonRateLimited:     "rate-limited",
	ReasonInternal:        "internal",
	ReasonIdle:            "idle",
	ReasonSessionGone:     "session-gone",
	ReasonProtocol:        "protocol",
	ReasonPeerReset:       "peer-reset",
	ReasonHandshakeStall:  "handshake-stall",
	ReasonShutdown:        "shutdown",
	ReasonOverloaded:      "overloaded",
	ReasonTooManyStreams:  "too-many-streams",
	ReasonUnauthorized:    "unauthorized",
	ReasonUnreachableEdge: "edge-unreachable",
}

func (r Reason) String() string {
	if int(r) < len(reasonNames) && reasonNames[r] != "" {
		return reasonNames[r]
	}
	return fmt.Sprintf("reason(%d)", uint8(r))
}

func (r Reason) Error() string { return "usp: " + r.String() }

type Fault uint8

const (
	FaultNone Fault = iota
	FaultEdge
	FaultExit
	FaultService
	FaultGeo
	FaultLocal
)

var faultNames = [...]string{
	FaultNone:    "none",
	FaultEdge:    "edge",
	FaultExit:    "exit",
	FaultService: "service",
	FaultGeo:     "geo",
	FaultLocal:   "local",
}

func (f Fault) String() string {
	if int(f) < len(faultNames) && faultNames[f] != "" {
		return faultNames[f]
	}
	return "fault(unknown)"
}

// Blames answers the only question the picker really has: does this outcome say
// something about the server, about the server's route to one destination, or
// about the destination itself.
func (r Reason) Blames() Fault {
	switch r {
	case ReasonNone, ReasonIdle, ReasonShutdown:
		return FaultNone
	case ReasonRefused, ReasonPeerReset:
		return FaultService
	case ReasonHostUnreachable, ReasonNetUnreachable, ReasonTimeout, ReasonHandshakeStall:
		return FaultExit
	case ReasonDNS:
		return FaultExit
	case ReasonGeoBlocked, ReasonPolicy:
		return FaultGeo
	case ReasonRateLimited, ReasonOverloaded, ReasonInternal, ReasonSessionGone,
		ReasonProtocol, ReasonTooManyStreams, ReasonUnauthorized, ReasonUnreachableEdge:
		return FaultEdge
	default:
		return FaultEdge
	}
}

// Retryable says whether the same request has any chance elsewhere. A refused
// connection is the destination's own answer and repeating it on another exit
// buys nothing but latency; an unreachable network is exactly what a second
// exit exists for.
func (r Reason) Retryable() bool {
	switch r.Blames() {
	case FaultExit, FaultGeo, FaultEdge:
		return true
	default:
		return false
	}
}
