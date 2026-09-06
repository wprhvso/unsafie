package edge

import (
	"os"
	"path/filepath"
	"testing"
	"time"
)

func TestStoreRoundTrips(t *testing.T) {
	store := NewStore(t.TempDir(), time.Minute)

	want := State{Edge: "waw", Slot: 1, Session: "aBcDeFgHiJkLmNoPqRsTuV", Up: 4096, Down: 8192}
	if err := store.Put(want); err != nil {
		t.Fatalf("put: %v", err)
	}

	got, ok := store.Take("waw", 1)
	if !ok {
		t.Fatal("what was just written could not be read back")
	}
	if got.Session != want.Session || got.Up != want.Up || got.Down != want.Down {
		t.Fatalf("state changed on the way through: %+v", got)
	}
}

// A resume that goes wrong must not be retried against the same stale offsets
// forever, so reading the state is also what removes it.
func TestTakeConsumes(t *testing.T) {
	store := NewStore(t.TempDir(), time.Minute)
	_ = store.Put(State{Edge: "de", Slot: 0, Session: "aBcDeFgHiJkLmNoPqRsTuV"})

	if _, ok := store.Take("de", 0); !ok {
		t.Fatal("first read found nothing")
	}
	if _, ok := store.Take("de", 0); ok {
		t.Fatal("the state survived being taken")
	}
}

func TestStateExpires(t *testing.T) {
	store := NewStore(t.TempDir(), time.Nanosecond)
	_ = store.Put(State{Edge: "clt", Slot: 0, Session: "aBcDeFgHiJkLmNoPqRsTuV"})

	time.Sleep(time.Millisecond)
	if _, ok := store.Take("clt", 0); ok {
		t.Fatal("an exit forgets a session in two minutes; the client must not offer an older one")
	}
}

func TestStateBelongsToOneEdgeAndSlot(t *testing.T) {
	dir := t.TempDir()
	store := NewStore(dir, time.Minute)
	_ = store.Put(State{Edge: "waw", Slot: 0, Session: "aBcDeFgHiJkLmNoPqRsTuV"})

	if _, ok := store.Take("waw", 1); ok {
		t.Fatal("slot 1 was handed slot 0's session")
	}
	if _, ok := store.Take("de", 0); ok {
		t.Fatal("another edge was handed this one's session")
	}
	if _, ok := store.Take("waw", 0); !ok {
		t.Fatal("the rightful owner lost it")
	}
}

func TestNoDirectoryMeansNoPersistence(t *testing.T) {
	var store *Store = NewStore("", time.Minute)
	if store != nil {
		t.Fatal("an empty directory should switch persistence off entirely")
	}
	if err := store.Put(State{Edge: "waw"}); err != nil {
		t.Fatalf("a disabled store must stay quiet: %v", err)
	}
	if _, ok := store.Take("waw", 0); ok {
		t.Fatal("a disabled store answered with a session")
	}
	store.Forget("waw", 0)
}

func TestGarbageIsIgnored(t *testing.T) {
	dir := t.TempDir()
	store := NewStore(dir, time.Minute)
	path := filepath.Join(dir, "session-waw-0.json")
	if err := os.WriteFile(path, []byte("{not json"), 0o600); err != nil {
		t.Fatal(err)
	}
	if _, ok := store.Take("waw", 0); ok {
		t.Fatal("garbage was accepted as state")
	}
	if _, err := os.Stat(path); !os.IsNotExist(err) {
		t.Fatal("garbage was left behind to be read again")
	}
}
