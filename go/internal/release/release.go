package release

import (
	"maps"
	"regexp"
	"slices"
	"strings"
)

const SignatureSuffix = ".sig"

var assets = map[string]string{
	"arm64-v8a":     "-arm64-v8a.apk",
	"armeabi-v7a":   "-armeabi-v7a.apk",
	"windows-amd64": "-amd64.exe",
	"linux-amd64":   "-linux-amd64",
}

type Manifest struct {
	Version string `json:"version"`
}

var versionPattern = regexp.MustCompile(`^[0-9]+(\.[0-9]+)*(-[0-9A-Za-z.]+)?$`)

func IsVersion(v string) bool { return versionPattern.MatchString(v) }

func Targets() []string { return slices.Sorted(maps.Keys(assets)) }

func Known(target string) bool { _, ok := assets[target]; return ok }

func Asset(version, target string) string {
	suffix, ok := assets[target]
	if !ok || !IsVersion(strings.TrimPrefix(version, "v")) {
		return ""
	}
	return "unsafie-v" + strings.TrimPrefix(version, "v") + suffix
}
