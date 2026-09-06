package metrics

import (
	"cmp"
	"fmt"
	"io"
	"math"
	"slices"
	"sort"
	"strconv"
	"strings"
	"sync"
	"sync/atomic"
	"time"
)

// A registry small enough to ship inside a VPN client and complete enough to
// answer "why did it pick that server" after the fact. Prometheus text format,
// because that is what already reads it on the other end.

type Kind uint8

const (
	KindCounter Kind = iota
	KindGauge
	KindHistogram
)

type Labels map[string]string

func (l Labels) key() string {
	if len(l) == 0 {
		return ""
	}
	names := make([]string, 0, len(l))
	for k := range l {
		names = append(names, k)
	}
	sort.Strings(names)

	var b strings.Builder
	for i, n := range names {
		if i > 0 {
			b.WriteByte(',')
		}
		b.WriteString(n)
		b.WriteByte('=')
		b.WriteString(l[n])
	}
	return b.String()
}

func (l Labels) render() string {
	if len(l) == 0 {
		return ""
	}
	names := make([]string, 0, len(l))
	for k := range l {
		names = append(names, k)
	}
	sort.Strings(names)

	var b strings.Builder
	b.WriteByte('{')
	for i, n := range names {
		if i > 0 {
			b.WriteByte(',')
		}
		b.WriteString(n)
		b.WriteString(`="`)
		b.WriteString(escape(l[n]))
		b.WriteByte('"')
	}
	b.WriteByte('}')
	return b.String()
}

func escape(v string) string {
	if !strings.ContainsAny(v, `\"`+"\n") {
		return v
	}
	r := strings.NewReplacer(`\`, `\\`, `"`, `\"`, "\n", `\n`)
	return r.Replace(v)
}

type Counter struct{ v atomic.Uint64 }

func (c *Counter) Inc()           { c.v.Add(1) }
func (c *Counter) Add(n uint64)   { c.v.Add(n) }
func (c *Counter) Value() uint64  { return c.v.Load() }
func (c *Counter) String() string { return strconv.FormatUint(c.v.Load(), 10) }

type Gauge struct{ v atomic.Int64 }

func (g *Gauge) Set(n int64)      { g.v.Store(n) }
func (g *Gauge) SetFloat(f float64) { g.v.Store(int64(f * 1e6)) }
func (g *Gauge) Float() float64   { return float64(g.v.Load()) / 1e6 }
func (g *Gauge) Add(n int64)      { g.v.Add(n) }
func (g *Gauge) Value() int64     { return g.v.Load() }

// Histogram uses a log-linear layout: fixed relative error everywhere instead
// of buckets that are precise where nothing happens and useless where the
// interesting tail is. Twelve octaves of four buckets covers a microsecond to
// a minute in 48 counters.
type Histogram struct {
	buckets [histBuckets]atomic.Uint64
	sum     atomic.Uint64
	count   atomic.Uint64
	unit    float64
}

const (
	histSub     = 4
	histOctaves = 22
	histBuckets = histSub * histOctaves
)

func NewHistogram(unit time.Duration) *Histogram {
	return &Histogram{unit: float64(unit)}
}

func bucketOf(v float64) int {
	if v <= 1 {
		return 0
	}
	e := math.Log2(v)
	idx := int(e * histSub)
	if idx < 0 {
		return 0
	}
	if idx >= histBuckets {
		return histBuckets - 1
	}
	return idx
}

func bucketBound(i int) float64 { return math.Exp2(float64(i+1) / histSub) }

func (h *Histogram) Observe(v float64) {
	h.buckets[bucketOf(v)].Add(1)
	h.count.Add(1)
	h.sum.Add(uint64(math.Max(v, 0)))
}

func (h *Histogram) ObserveDuration(d time.Duration) {
	unit := h.unit
	if unit == 0 {
		unit = float64(time.Millisecond)
	}
	h.Observe(float64(d) / unit)
}

func (h *Histogram) Count() uint64 { return h.count.Load() }

// Quantile reads the sketch back. Good enough to decide a hedging delay, which
// is the only thing that asks.
func (h *Histogram) Quantile(q float64) float64 {
	total := h.count.Load()
	if total == 0 {
		return 0
	}
	want := uint64(math.Ceil(q * float64(total)))
	var seen uint64
	for i := range h.buckets {
		seen += h.buckets[i].Load()
		if seen >= want {
			return bucketBound(i)
		}
	}
	return bucketBound(histBuckets - 1)
}

type series struct {
	name   string
	help   string
	kind   Kind
	labels Labels

	counter *Counter
	gauge   *Gauge
	hist    *Histogram
}

type Registry struct {
	mu     sync.RWMutex
	series map[string]*series
	order  []*series
	unit   time.Duration
}

func NewRegistry() *Registry {
	return &Registry{series: map[string]*series{}, unit: time.Millisecond}
}

var Default = NewRegistry()

func (r *Registry) find(name string, l Labels, kind Kind, help string) *series {
	key := name + "|" + l.key()

	r.mu.RLock()
	s := r.series[key]
	r.mu.RUnlock()
	if s != nil {
		return s
	}

	r.mu.Lock()
	defer r.mu.Unlock()
	if s = r.series[key]; s != nil {
		return s
	}

	s = &series{name: name, help: help, kind: kind, labels: l}
	switch kind {
	case KindCounter:
		s.counter = &Counter{}
	case KindGauge:
		s.gauge = &Gauge{}
	case KindHistogram:
		s.hist = NewHistogram(r.unit)
	}
	r.series[key] = s
	r.order = append(r.order, s)
	return s
}

func (r *Registry) Counter(name, help string, l Labels) *Counter {
	return r.find(name, l, KindCounter, help).counter
}

func (r *Registry) Gauge(name, help string, l Labels) *Gauge {
	return r.find(name, l, KindGauge, help).gauge
}

func (r *Registry) Histogram(name, help string, l Labels) *Histogram {
	return r.find(name, l, KindHistogram, help).hist
}

func Counter(name, help string, l Labels) *Counter { return Default.Counter(name, help, l) }
func Gauge(name, help string, l Labels) *Gauge     { return Default.Gauge(name, help, l) }
func Histogram(name, help string, l Labels) *Histogram {
	return Default.Histogram(name, help, l)
}

func (r *Registry) snapshot() []*series {
	r.mu.RLock()
	defer r.mu.RUnlock()
	out := slices.Clone(r.order)
	slices.SortFunc(out, func(a, b *series) int {
		if c := cmp.Compare(a.name, b.name); c != 0 {
			return c
		}
		return cmp.Compare(a.labels.key(), b.labels.key())
	})
	return out
}

func (r *Registry) WriteTo(w io.Writer) (int64, error) {
	var b strings.Builder
	lastName := ""

	for _, s := range r.snapshot() {
		if s.name != lastName {
			lastName = s.name
			if s.help != "" {
				fmt.Fprintf(&b, "# HELP %s %s\n", s.name, s.help)
			}
			fmt.Fprintf(&b, "# TYPE %s %s\n", s.name, typeName(s.kind))
		}
		labels := s.labels.render()
		switch s.kind {
		case KindCounter:
			fmt.Fprintf(&b, "%s%s %d\n", s.name, labels, s.counter.Value())
		case KindGauge:
			fmt.Fprintf(&b, "%s%s %s\n", s.name, labels, trim(s.gauge.Float()))
		case KindHistogram:
			writeHistogram(&b, s)
		}
	}
	n, err := io.WriteString(w, b.String())
	return int64(n), err
}

func writeHistogram(b *strings.Builder, s *series) {
	var seen uint64
	base := s.labels
	for i := range s.hist.buckets {
		seen += s.hist.buckets[i].Load()
		if s.hist.buckets[i].Load() == 0 && seen == 0 {
			continue
		}
		l := make(Labels, len(base)+1)
		for k, v := range base {
			l[k] = v
		}
		l["le"] = trim(bucketBound(i))
		fmt.Fprintf(b, "%s_bucket%s %d\n", s.name, l.render(), seen)
	}
	l := make(Labels, len(base)+1)
	for k, v := range base {
		l[k] = v
	}
	l["le"] = "+Inf"
	fmt.Fprintf(b, "%s_bucket%s %d\n", s.name, l.render(), s.hist.count.Load())
	fmt.Fprintf(b, "%s_sum%s %d\n", s.name, base.render(), s.hist.sum.Load())
	fmt.Fprintf(b, "%s_count%s %d\n", s.name, base.render(), s.hist.count.Load())
}

func typeName(k Kind) string {
	switch k {
	case KindCounter:
		return "counter"
	case KindGauge:
		return "gauge"
	default:
		return "histogram"
	}
}

func trim(f float64) string {
	if f == math.Trunc(f) && math.Abs(f) < 1e15 {
		return strconv.FormatInt(int64(f), 10)
	}
	return strconv.FormatFloat(f, 'g', 6, 64)
}

func (r *Registry) Text() string {
	var b strings.Builder
	_, _ = r.WriteTo(&b)
	return b.String()
}
