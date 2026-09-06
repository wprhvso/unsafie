package fleet

import (
	"math"
	"math/rand/v2"
	"testing"
	"time"

	"unsafie/internal/service"
)

func TestBetaForgetsOnASchedule(t *testing.T) {
	now := time.Now()
	b := NewBeta(time.Minute)
	for range 40 {
		b.Observe(false, 1, now)
	}
	broken := b.Mean(now)
	if broken > 0.1 {
		t.Fatalf("forty failures left the belief at %.3f", broken)
	}

	later := now.Add(10 * time.Minute)
	if healed := b.Mean(later); healed < 0.4 {
		t.Fatalf("after ten half lives the belief is still %.3f", healed)
	}
}

func TestThompsonSamplesStayInRangeAndFollowEvidence(t *testing.T) {
	now := time.Now()
	rng := rand.New(rand.NewPCG(1, 2))

	good := NewBeta(time.Hour)
	bad := NewBeta(time.Hour)
	for range 50 {
		good.Observe(true, 1, now)
		bad.Observe(false, 1, now)
	}

	wins := 0
	for range 400 {
		g, b := good.Sample(rng, now), bad.Sample(rng, now)
		if g < 0 || g > 1 || b < 0 || b > 1 {
			t.Fatalf("sample outside [0,1]: %.3f %.3f", g, b)
		}
		if g > b {
			wins++
		}
	}
	if wins < 380 {
		t.Fatalf("the healthy arm only won %d of 400 draws", wins)
	}
}

func TestAccrualRisesWithSilence(t *testing.T) {
	a := NewAccrual(16)
	now := time.Now()
	for i := range 20 {
		a.Heartbeat(now.Add(time.Duration(i) * time.Second))
	}
	last := now.Add(19 * time.Second)

	if phi := a.Phi(last.Add(time.Second)); phi > 3 {
		t.Fatalf("a heartbeat on time already reads as suspicious: phi=%.2f", phi)
	}
	quiet := a.Phi(last.Add(30 * time.Second))
	if quiet < 8 || math.IsNaN(quiet) {
		t.Fatalf("thirty seconds of silence reads as phi=%.2f", quiet)
	}
}

func TestBreakerOpensAndProbesOnce(t *testing.T) {
	now := time.Now()
	b := NewBreaker(3, 50*time.Millisecond, time.Second)

	for range 3 {
		if !b.Allow(now) {
			t.Fatal("the breaker closed before it had a reason")
		}
		b.Failure(now)
	}
	if b.State() != StateOpen {
		t.Fatalf("state is %s after three consecutive failures", b.State())
	}
	if b.Allow(now) {
		t.Fatal("an open breaker let a call through immediately")
	}

	later := now.Add(time.Second)
	if !b.Allow(later) {
		t.Fatal("the breaker never went half open")
	}
	if b.Allow(later) {
		t.Fatal("half open let a second probe through")
	}
	b.Success(later)
	if b.State() != StateClosed {
		t.Fatalf("a successful probe left the breaker %s", b.State())
	}
}

func TestEWMATracksTheRecentPast(t *testing.T) {
	e := NewEWMA(time.Second)
	now := time.Now()
	e.Add(100, now)
	for i := 1; i <= 10; i++ {
		e.Add(10, now.Add(time.Duration(i)*time.Second))
	}
	if v := e.Value(); v > 12 {
		t.Fatalf("the average is still %.1f after ten time constants at 10", v)
	}
}

func TestTableIsBoundedAndKeyedByService(t *testing.T) {
	tbl := NewTable(32, time.Minute, time.Second)
	for i := range 200 {
		tbl.Cell("waw", service.Key(hostFor(i)))
	}
	if n := tbl.Len(); n > 32 {
		t.Fatalf("the table grew to %d cells with a limit of 32", n)
	}
}

func TestServiceKeyGroupsWhatFailsTogether(t *testing.T) {
	if a, b := service.Key("s3.eu-central-1.amazonaws.com"), service.Key("s3.us-east-1.amazonaws.com"); a != b {
		t.Fatalf("two regions of one service became %q and %q", a, b)
	}
	if got := service.Key("93.184.216.34"); got != "93.184.216.0/24" {
		t.Fatalf("literal address became %q", got)
	}
	if got := service.Key("api.telegram.org"); got != "telegram.org" {
		t.Fatalf("registrable domain became %q", got)
	}
}

func hostFor(i int) string {
	letters := "abcdefghijklmnopqrstuvwxyz"
	return string([]byte{letters[i%26], letters[(i/26)%26], letters[(i/676)%26]}) + ".example.com"
}
