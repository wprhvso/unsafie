package edge

import (
	"encoding/json"
	"os"
	"path/filepath"
	"strconv"
	"sync"
	"time"
)

const stateVersion = 1

// State is the little that has to outlive the process for a session to be
// picked up rather than replaced: what it was called and how far each direction
// had got. The frames themselves are deliberately not here — a client that died
// has no application sockets left to carry, so there is nothing to replay, only
// a place to continue from.
type State struct {
	Version int    `json:"v"`
	Edge    string `json:"edge"`
	Slot    int    `json:"slot"`
	Session string `json:"session"`
	Up      int64  `json:"up"`
	Down    int64  `json:"down"`
	SavedAt int64  `json:"saved_at"`
}

// Store keeps one file per (edge, slot). Nothing in it is secret in the
// cryptographic sense and everything in it is worthless after a couple of
// minutes, which is why it is a plain file with a short life rather than
// anything more careful.
type Store struct {
	dir string
	ttl time.Duration
	mu  sync.Mutex
}

func NewStore(dir string, ttl time.Duration) *Store {
	if dir == "" {
		return nil
	}
	if ttl <= 0 {
		ttl = 90 * time.Second
	}
	return &Store{dir: dir, ttl: ttl}
}

func (s *Store) path(edge string, slot int) string {
	return filepath.Join(s.dir, "session-"+edge+"-"+strconv.Itoa(slot)+".json")
}

// Take reads the state and removes it in one step. A resume that goes wrong
// must not be retried against the same stale offsets forever; consuming the
// file makes the next attempt an honest new session.
func (s *Store) Take(edge string, slot int) (State, bool) {
	if s == nil {
		return State{}, false
	}

	s.mu.Lock()
	defer s.mu.Unlock()

	path := s.path(edge, slot)
	raw, err := os.ReadFile(path)
	_ = os.Remove(path)
	if err != nil {
		return State{}, false
	}

	var st State
	if err := json.Unmarshal(raw, &st); err != nil {
		return State{}, false
	}
	if st.Version != stateVersion || st.Edge != edge || st.Slot != slot || st.Session == "" {
		return State{}, false
	}
	if time.Since(time.Unix(0, st.SavedAt)) > s.ttl {
		return State{}, false
	}
	return st, true
}

func (s *Store) Put(st State) error {
	if s == nil {
		return nil
	}

	s.mu.Lock()
	defer s.mu.Unlock()

	if err := os.MkdirAll(s.dir, 0o700); err != nil {
		return err
	}

	st.Version = stateVersion
	st.SavedAt = time.Now().UnixNano()
	raw, err := json.Marshal(st)
	if err != nil {
		return err
	}

	final := s.path(st.Edge, st.Slot)
	temp := final + ".tmp"
	if err := os.WriteFile(temp, raw, 0o600); err != nil {
		return err
	}
	return os.Rename(temp, final)
}

func (s *Store) Forget(edge string, slot int) {
	if s == nil {
		return
	}
	s.mu.Lock()
	_ = os.Remove(s.path(edge, slot))
	s.mu.Unlock()
}
