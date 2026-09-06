package sysexec

import (
	"context"
	"os/exec"
	"slices"
	"strings"
	"sync"

	"unsafie/internal/logging"
)

type Runner interface {
	Run(ctx context.Context, name string, args ...string) error
	Try(ctx context.Context, name string, args ...string)
	Output(ctx context.Context, name string, args ...string) ([]byte, error)
}

type OS struct{}

func New() Runner { return OS{} }

func (OS) Run(ctx context.Context, name string, args ...string) error {
	return exec.CommandContext(ctx, name, args...).Run()
}

func (r OS) Try(ctx context.Context, name string, args ...string) {
	if err := r.Run(ctx, name, args...); err != nil {
		logging.Infof("%s %s: %v", name, strings.Join(args, " "), err)
	}
}

func (OS) Output(ctx context.Context, name string, args ...string) ([]byte, error) {
	return exec.CommandContext(ctx, name, args...).Output()
}

type Recorder struct {
	mu   sync.Mutex
	runs []string

	fail func(name string, args []string) error

	Stdout func(name string, args []string) ([]byte, error)
}

func NewRecorder() *Recorder { return &Recorder{} }

func (r *Recorder) SetFail(f func(name string, args []string) error) {
	r.mu.Lock()
	r.fail = f
	r.mu.Unlock()
}

func (r *Recorder) Run(_ context.Context, name string, args ...string) error {
	r.mu.Lock()
	r.runs = append(r.runs, name+" "+strings.Join(args, " "))
	fail := r.fail
	r.mu.Unlock()

	if fail != nil {
		return fail(name, args)
	}
	return nil
}

func (r *Recorder) Try(ctx context.Context, name string, args ...string) {
	_ = r.Run(ctx, name, args...)
}

func (r *Recorder) Output(ctx context.Context, name string, args ...string) ([]byte, error) {
	if r.Stdout != nil {
		if err := r.Run(ctx, name, args...); err != nil {
			return nil, err
		}
		return r.Stdout(name, args)
	}
	return nil, r.Run(ctx, name, args...)
}

func (r *Recorder) Calls() []string {
	r.mu.Lock()
	defer r.mu.Unlock()
	return slices.Clone(r.runs)
}

func (r *Recorder) Contains(want string) bool {
	return slices.Contains(r.Calls(), want)
}
