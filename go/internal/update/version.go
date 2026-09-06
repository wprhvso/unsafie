package update

import (
	"cmp"
	"strconv"
	"strings"

	"unsafie/internal/release"
)

func Enabled(version, baseURL, key, token string) bool {
	return IsReleaseVersion(version) && baseURL != "" && key != "" && token != ""
}

func IsReleaseVersion(v string) bool {
	return release.IsVersion(strings.TrimPrefix(strings.TrimSpace(v), "v"))
}

func AssetURL(base, version, target string) string {
	return strings.TrimSuffix(base, "/") + "/" + version + "/" + target
}

func SignatureURL(base, version, target string) string {
	return AssetURL(base, version, target) + release.SignatureSuffix
}

func IsNewer(current, candidate string) bool {
	return Compare(candidate, current) > 0
}

func Compare(left, right string) int {
	a, b := releaseNumbers(left), releaseNumbers(right)
	for i := range max(len(a), len(b)) {
		if order := cmp.Compare(at(a, i), at(b, i)); order != 0 {
			return order
		}
	}
	return cmp.Compare(releaseRank(left), releaseRank(right))
}

func releaseNumbers(version string) []int {
	version = strings.TrimPrefix(strings.TrimSpace(version), "v")
	version, _, _ = strings.Cut(version, "-")

	parts := strings.Split(version, ".")
	out := make([]int, len(parts))
	for i, p := range parts {
		out[i], _ = strconv.Atoi(p)
	}
	return out
}

func releaseRank(version string) int {
	if strings.Contains(strings.TrimSpace(version), "-") {
		return 0
	}
	return 1
}

func at(numbers []int, i int) int {
	if i < len(numbers) {
		return numbers[i]
	}
	return 0
}
