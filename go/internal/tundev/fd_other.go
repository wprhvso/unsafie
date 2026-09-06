//go:build !android

package tundev

func PrepareFD(fd int) {} //nolint:unused // only the android build calls it

func CloseFD(fd int) error { return nil }
