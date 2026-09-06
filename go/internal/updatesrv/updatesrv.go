package updatesrv

import (
	"crypto/subtle"
	"encoding/json"
	"errors"
	"net/http"
	"os"
	"path/filepath"
	"strings"

	"unsafie/internal/release"
)

const currentFile = "current"

var errBadState = errors.New("updatesrv: the current version on disk is not a release number")

type Server struct {
	Path  string
	Dir   string
	Token string
}

func (s *Server) Version() (string, error) {
	b, err := os.ReadFile(filepath.Join(s.Dir, currentFile))
	if errors.Is(err, os.ErrNotExist) {
		return "", nil
	}
	if err != nil {
		return "", err
	}
	v := strings.TrimSpace(string(b))
	if v == "" {
		return "", nil
	}
	if !release.IsVersion(v) {
		return "", errBadState
	}
	return v, nil
}

func (s *Server) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	switch {
	case r.URL.Path == s.Path:
		s.manifest(w, r)
	case strings.HasPrefix(r.URL.Path, s.Path+"/"):
		s.download(w, r, strings.TrimPrefix(r.URL.Path, s.Path+"/"))
	default:
		http.NotFound(w, r)
	}
}

func (s *Server) manifest(w http.ResponseWriter, r *http.Request) {
	if !s.allowMethod(w, r) || !s.authorize(w, r) {
		return
	}
	v, err := s.Version()
	if err != nil {
		http.Error(w, "release state unreadable", http.StatusInternalServerError)
		return
	}
	if v == "" {
		http.Error(w, "no release", http.StatusNotFound)
		return
	}
	body, err := json.Marshal(release.Manifest{Version: v})
	if err != nil {
		http.Error(w, "cannot encode", http.StatusInternalServerError)
		return
	}
	w.Header().Set("Content-Type", "application/json")
	w.Header().Set("Cache-Control", "no-store")
	if r.Method == http.MethodHead {
		return
	}
	_, _ = w.Write(body)
}

func (s *Server) download(w http.ResponseWriter, r *http.Request, rest string) {
	if !s.allowMethod(w, r) || !s.authorize(w, r) {
		return
	}
	version, target, ok := strings.Cut(rest, "/")
	target, signature := strings.CutSuffix(target, release.SignatureSuffix)
	if !ok || strings.Contains(target, "/") || !release.IsVersion(version) || !release.Known(target) {
		http.NotFound(w, r)
		return
	}
	asset := release.Asset(version, target)
	if asset == "" {
		http.NotFound(w, r)
		return
	}
	if signature {
		asset += release.SignatureSuffix
	}

	path := filepath.Join(s.Dir, version, asset)
	if !strings.HasPrefix(path, filepath.Clean(s.Dir)+string(filepath.Separator)) {
		http.NotFound(w, r)
		return
	}
	f, err := os.Open(path)
	if err != nil {
		http.NotFound(w, r)
		return
	}
	defer func() { _ = f.Close() }()

	info, err := f.Stat()
	if err != nil || !info.Mode().IsRegular() {
		http.NotFound(w, r)
		return
	}

	if signature {
		w.Header().Set("Content-Type", "text/plain; charset=utf-8")
	} else {
		w.Header().Set("Content-Type", "application/octet-stream")
	}
	w.Header().Set("Cache-Control", "no-store")
	http.ServeContent(w, r, asset, info.ModTime(), f)
}

func (s *Server) allowMethod(w http.ResponseWriter, r *http.Request) bool {
	if r.Method == http.MethodGet || r.Method == http.MethodHead {
		return true
	}
	w.Header().Set("Allow", "GET, HEAD")
	http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
	return false
}

func (s *Server) authorize(w http.ResponseWriter, r *http.Request) bool {
	if s.Token != "" {
		got, ok := strings.CutPrefix(r.Header.Get("Authorization"), "Bearer ")
		if ok && subtle.ConstantTimeCompare([]byte(strings.TrimSpace(got)), []byte(s.Token)) == 1 {
			return true
		}
	}
	w.Header().Set("WWW-Authenticate", `Bearer realm="unsafie"`)
	http.Error(w, "unauthorized", http.StatusUnauthorized)
	return false
}
