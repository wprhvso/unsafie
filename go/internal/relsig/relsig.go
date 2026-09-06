package relsig

import (
	"crypto/ed25519"
	"crypto/sha256"
	"encoding/base64"
	"errors"
	"fmt"
	"hash"
	"io"
	"strings"
)

const statementPrefix = "unsafie-release/1"

const MaxSignatureSize = 512

var (
	ErrBadSignature = errors.New("signature does not match the artifact")

	ErrBadField = errors.New("field is empty or contains a newline")

	errBadKey = errors.New("not a base64 ed25519 key")
)

var encoding = base64.StdEncoding

func Statement(version, target string, digest []byte) (string, error) {
	for _, field := range []string{version, target} {
		if field == "" || strings.ContainsAny(field, "\n\r") {
			return "", fmt.Errorf("%w: %q", ErrBadField, field)
		}
	}
	return fmt.Sprintf("%s\n%s\n%s\n%x\n", statementPrefix, version, target, digest), nil
}

func Hasher() hash.Hash { return sha256.New() }

func Sign(key ed25519.PrivateKey, version, target string, digest []byte) (string, error) {
	statement, err := Statement(version, target, digest)
	if err != nil {
		return "", err
	}
	return encoding.EncodeToString(ed25519.Sign(key, []byte(statement))), nil
}

func Verify(key ed25519.PublicKey, version, target string, digest []byte, signature string) error {
	statement, err := Statement(version, target, digest)
	if err != nil {
		return fmt.Errorf("%w: %w", ErrBadSignature, err)
	}
	raw, err := encoding.DecodeString(strings.TrimSpace(signature))
	if err != nil {
		return fmt.Errorf("%w: not base64", ErrBadSignature)
	}
	if len(raw) != ed25519.SignatureSize {
		return fmt.Errorf("%w: %d bytes, want %d", ErrBadSignature, len(raw), ed25519.SignatureSize)
	}
	if !ed25519.Verify(key, []byte(statement), raw) {
		return ErrBadSignature
	}
	return nil
}

func Generate() (public, private string, err error) {
	pub, priv, err := ed25519.GenerateKey(nil)
	if err != nil {
		return "", "", err
	}
	return encoding.EncodeToString(pub), encoding.EncodeToString(priv.Seed()), nil
}

func PublicKey(s string) (ed25519.PublicKey, error) {
	raw, err := encoding.DecodeString(strings.TrimSpace(s))
	if err != nil {
		return nil, errBadKey
	}
	if len(raw) != ed25519.PublicKeySize {
		return nil, fmt.Errorf("%w: %d bytes, want %d", errBadKey, len(raw), ed25519.PublicKeySize)
	}
	return raw, nil
}

func PrivateKey(s string) (ed25519.PrivateKey, error) {
	raw, err := encoding.DecodeString(strings.TrimSpace(s))
	if err != nil {
		return nil, errBadKey
	}
	if len(raw) != ed25519.SeedSize {
		return nil, fmt.Errorf("%w: %d bytes, want %d", errBadKey, len(raw), ed25519.SeedSize)
	}
	return ed25519.NewKeyFromSeed(raw), nil
}

func Digest(r io.Reader) ([]byte, error) {
	h := Hasher()
	if _, err := io.Copy(h, r); err != nil {
		return nil, err
	}
	return h.Sum(nil), nil
}
