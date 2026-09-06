//go:build android

package main

/*
#cgo LDFLAGS: -llog

#include <jni.h>
#include <android/log.h>
#include <stdlib.h>

static inline void log_info(const char* msg) {
    __android_log_write(ANDROID_LOG_INFO, "UnsafieCore", msg);
}
*/
import "C"

import (
	"bufio"
	"log/slog"
	"os"
	"sync"
	"unsafe"

	"unsafie/internal/logging"
	"unsafie/internal/tundev"
)

type androidPlatform struct{ basePlatform }

func androidLog(level slog.Level, msg string) {
	cMsg := C.CString(logging.Prefix(level) + msg)
	defer C.free(unsafe.Pointer(cMsg))
	C.log_info(cMsg)
}

var androidInitOnce sync.Once

func (androidPlatform) Init() {
	androidInitOnce.Do(func() {
		r, w, err := os.Pipe()
		if err != nil {
			logging.Warnf("failed to create log pipe: %v", err)
			return
		}
		os.Stdout = w
		os.Stderr = w

		go func() {
			scanner := bufio.NewScanner(r)
			for scanner.Scan() {
				logging.Infof("%s", scanner.Text())
			}
		}()
	})
}

func init() {
	logging.SetDefault(logging.NewLine(androidLog))
	plat = androidPlatform{}
}

//export Java_com_unsafie_vpn_MyVpnService_startGoCore
func Java_com_unsafie_vpn_MyVpnService_startGoCore(env *C.JNIEnv, clazz C.jclass, fd, mtu C.jint) {
	vpnFd := int(fd)
	logging.Infof("Received FD %d (mtu %d) from Android VpnService.", vpnFd, int(mtu))
	tundev.PrepareFD(vpnFd)
	startVpnEngine(vpnFd, int(mtu))
}

//export Java_com_unsafie_vpn_MyVpnService_stopGoCore
func Java_com_unsafie_vpn_MyVpnService_stopGoCore(env *C.JNIEnv, clazz C.jclass) {
	stopVpnEngine()
	logging.Infof("Core engine stopped.")
}

//export Java_com_unsafie_vpn_MyVpnService_isGoCoreRunning
func Java_com_unsafie_vpn_MyVpnService_isGoCoreRunning(env *C.JNIEnv, clazz C.jclass) C.jboolean {
	if current.Load() != nil {
		return C.JNI_TRUE
	}
	return C.JNI_FALSE
}

//export Java_com_unsafie_vpn_MyVpnService_logCoreStatus
func Java_com_unsafie_vpn_MyVpnService_logCoreStatus(env *C.JNIEnv, clazz C.jclass) {
	e := current.Load()
	if e == nil || e.fleet == nil {
		logging.Infof("Fleet: stopped")
		return
	}
	logging.Infof("Fleet: %s", e.fleet.Status())
}

func main() {}
