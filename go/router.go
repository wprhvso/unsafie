package main

import (
	"unsafie/internal/policy"
)

const localDNSPort = "53"

var localDNSAddr = "127.0.0.1:10533"

func (e *engine) decide(address string) policy.Decision { return e.router.Decide(address) }
