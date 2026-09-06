package main

import (
	_ "embed"

	"unsafie/internal/rules"
)

//go:embed rules.bin
var rulesData []byte

var (
	ruleSet    *rules.Set
	errRuleSet error
)

func init() {
	ruleSet, errRuleSet = rules.Load(rulesData)
}
