package main

import (
	"time"

	"unsafie/internal/logging"
	"unsafie/internal/tundev"
	"unsafie/internal/tunnet"
)

const tunRetryDelay = time.Second

func (e *engine) runTun() {
	var lastErr string

	for e.ctx.Err() == nil {
		err := e.serveTun()
		switch {
		case err == nil:
			lastErr = ""
		case err.Error() != lastErr:
			lastErr = err.Error()
			logging.Infof("TUN %s: %v", tunIface, err)
		}

		select {
		case <-e.ctx.Done():
			return
		case <-time.After(tunRetryDelay):
		}
	}
}

func (e *engine) serveTun() error {
	dev, err := tundev.Open(e.ctx, e.tunCfg(), e.fd)
	if err != nil {
		return err
	}
	defer dev.Release()

	s, err := tunnet.New(e.ctx, dev, e.dial)
	if err != nil {
		return err
	}
	defer s.Close()

	logging.Infof("TUN %s is up (mtu %d)", tunIface, e.mtu)
	defer logging.Infof("TUN %s is down", tunIface)

	select {
	case <-e.ctx.Done():
	case <-dev.Dead():
		return tunnet.ErrDeviceGone
	}
	return nil
}
