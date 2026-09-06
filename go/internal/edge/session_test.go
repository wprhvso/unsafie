package edge

import (
	"strings"
	"testing"
)

func TestSessionNamesCarryTheSlotAndEnoughRandomness(t *testing.T) {
	const alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"

	seen := make(map[string]bool, 4096)
	for range 4096 {
		id := mintSession("bc")
		if len(id) != SessionIDLen {
			t.Fatalf("%q is %d characters, want %d", id, len(id), SessionIDLen)
		}
		if id[0] != 'b' && id[0] != 'c' {
			t.Fatalf("%q does not start with a configured slot", id)
		}
		for i := range id {
			if !strings.ContainsRune(alphabet, rune(id[i])) {
				t.Fatalf("%q contains %q, which nginx would not match", id, id[i])
			}
		}
		if seen[id] {
			t.Fatalf("%q was minted twice in 4096 draws", id)
		}
		seen[id] = true
	}
}

func TestSessionNamesFallBackToTheDefaultSlot(t *testing.T) {
	id := mintSession("")
	if !strings.HasPrefix(id, DefaultSlots) {
		t.Fatalf("%q does not start with the default slot %q", id, DefaultSlots)
	}
}
