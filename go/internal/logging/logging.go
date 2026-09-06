package logging

import (
	"context"
	"fmt"
	"io"
	"log/slog"
	"sync/atomic"
	"time"
)

type Logger struct{ h slog.Handler }

func New(h slog.Handler) *Logger { return &Logger{h: h} }

func (l *Logger) Infof(format string, args ...any)  { l.logf(slog.LevelInfo, format, args...) }
func (l *Logger) Warnf(format string, args ...any)  { l.logf(slog.LevelWarn, format, args...) }
func (l *Logger) Errorf(format string, args ...any) { l.logf(slog.LevelError, format, args...) }

func (l *Logger) logf(level slog.Level, format string, args ...any) {
	if l == nil || l.h == nil || !l.h.Enabled(context.Background(), level) {
		return
	}
	r := slog.NewRecord(time.Now(), level, fmt.Sprintf(format, args...), 0)
	_ = l.h.Handle(context.Background(), r)
}

var current atomic.Pointer[Logger]

func SetDefault(l *Logger) { current.Store(l) }

func Default() *Logger { return current.Load() }

func Infof(format string, args ...any)  { Default().Infof(format, args...) }
func Warnf(format string, args ...any)  { Default().Warnf(format, args...) }
func Errorf(format string, args ...any) { Default().Errorf(format, args...) }

type LineHandler struct {
	Level slog.Level
	Write func(level slog.Level, msg string)
}

func (h *LineHandler) Enabled(_ context.Context, level slog.Level) bool { return level >= h.Level }

func (h *LineHandler) Handle(_ context.Context, r slog.Record) error {
	h.Write(r.Level, r.Message)
	return nil
}

func (h *LineHandler) WithAttrs([]slog.Attr) slog.Handler { return h }
func (h *LineHandler) WithGroup(string) slog.Handler      { return h }

func NewLine(write func(level slog.Level, msg string)) *Logger {
	return New(&LineHandler{Level: slog.LevelInfo, Write: write})
}

func NewWriter(w io.Writer) *Logger {
	return NewLine(func(level slog.Level, msg string) {
		_, _ = fmt.Fprintf(w, "[unsafie] %s%s\n", Prefix(level), msg)
	})
}

func Prefix(level slog.Level) string {
	switch {
	case level >= slog.LevelError:
		return "CRITICAL: "
	case level >= slog.LevelWarn:
		return "Warning: "
	default:
		return ""
	}
}
