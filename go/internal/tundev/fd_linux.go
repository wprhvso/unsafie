//go:build linux && !android

package tundev

func dupFD(fd int) (int, error) { return fd, nil }
