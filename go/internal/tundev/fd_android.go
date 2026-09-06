//go:build android

package tundev

import (
	"syscall"

	"unsafie/internal/logging"
)

func PrepareFD(fd int) {
	if fd <= 0 {
		return
	}
	if err := syscall.SetNonblock(fd, true); err != nil {
		logging.Warnf("SetNonblock(%d) failed: %v", fd, err)
		return
	}
	logging.Infof("TUN fd %d set to non-blocking mode", fd)
}

func CloseFD(fd int) error {
	return syscall.Close(fd)
}

func dupFD(fd int) (int, error) {
	return syscall.Dup(fd)
}
