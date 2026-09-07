<script>
  import { onMount } from 'svelte';

  let { cost = 0, budget = null, context = 0, limit = 200000, tokens = 0, live = false } = $props();

  const EASE = 0.18;
  const EPS = 0.00002;

  let shown = $state(0);
  let frame;

  onMount(() => {
    const tick = () => {
      const gap = cost - shown;
      shown = Math.abs(gap) < EPS ? cost : shown + gap * EASE;
      frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  });

  const pct = (value, max) => (max > 0 ? Math.min(100, Math.max(0, (value / max) * 100)) : 0);

  const contextPct = $derived(pct(context, limit));
  const budgetPct = $derived(budget ? pct(cost, budget) : 0);
  const left = $derived(budget === null ? null : Math.max(budget - cost, 0));

  const tone = (value) => (value >= 90 ? 'bad' : value >= 70 ? 'warn' : 'ok');

  const compact = (n) =>
    n >= 1e6
      ? `${(n / 1e6).toFixed(1)}M`
      : n >= 1000
        ? `${Math.round(n / 1000)}k`
        : String(Math.round(n));

  const money = (value, digits = 4) => `$${Number(value ?? 0).toFixed(digits)}`;
</script>

<section class="meters">
  <div class="money">
    <div class="spent">
      <span class="label">spent</span>
      <span class="value mono" class:live>{money(shown)}</span>
    </div>
    <div class="rest">
      <span class="label">left</span>
      <span class="value small mono">{left === null ? '—' : money(left, 2)}</span>
    </div>
  </div>

  <div class="bars">
    <div class="row">
      <span class="tag">context</span>
      <div
        class="track"
        role="progressbar"
        aria-label="context filled"
        aria-valuenow={Math.round(contextPct)}
        aria-valuemin="0"
        aria-valuemax="100"
      >
        <div class="fill {tone(contextPct)}" style="width:{contextPct}%"></div>
      </div>
      <span class="num mono">{compact(context)}/{compact(limit)}</span>
      <span class="pc mono {tone(contextPct)}">{contextPct.toFixed(0)}%</span>
    </div>

    <div class="row">
      <span class="tag">budget</span>
      <div
        class="track"
        role="progressbar"
        aria-label="budget used"
        aria-valuenow={Math.round(budgetPct)}
        aria-valuemin="0"
        aria-valuemax="100"
      >
        <div class="fill {tone(budgetPct)}" style="width:{budgetPct}%"></div>
      </div>
      <span class="num mono">{budget === null ? '—' : money(budget, 2)}</span>
      <span class="pc mono {tone(budgetPct)}"
        >{budget === null ? '—' : `${budgetPct.toFixed(1)}%`}</span
      >
    </div>
  </div>

  <div class="tok">
    <span class="label">tokens</span>
    <span class="value small mono">{compact(tokens)}</span>
  </div>
</section>

<style>
  .meters {
    display: flex;
    align-items: center;
    gap: 0.9rem;
    padding: 0.4rem 0.9rem 0.5rem;
    border-bottom: 1px solid var(--border);
    background: var(--live-bar);
    backdrop-filter: saturate(140%) blur(10px);
  }

  .money {
    flex: 0 0 auto;
    display: flex;
    align-items: baseline;
    gap: 0.7rem;
  }

  .spent,
  .rest,
  .tok {
    display: flex;
    flex-direction: column;
    gap: 0.05rem;
    line-height: 1.15;
  }

  .tok {
    flex: 0 0 auto;
    align-items: flex-end;
  }

  .label {
    font-size: 0.6rem;
    letter-spacing: 0.07em;
    text-transform: uppercase;
    color: var(--muted);
  }

  .value {
    font-variant-numeric: tabular-nums;
    font-size: 1.1rem;
    font-weight: 600;
    white-space: nowrap;
  }

  .value.small {
    font-size: 0.8rem;
    font-weight: 500;
    color: var(--muted);
  }

  .value.live {
    color: var(--accent);
  }

  .bars {
    flex: 1 1 auto;
    min-width: 0;
    display: flex;
    flex-direction: column;
    gap: 0.28rem;
  }

  .row {
    display: flex;
    align-items: center;
    gap: 0.45rem;
    font-size: 0.7rem;
    color: var(--muted);
    white-space: nowrap;
  }

  .tag {
    flex: 0 0 auto;
    width: 3.6rem;
    letter-spacing: 0.05em;
    text-transform: uppercase;
    font-size: 0.6rem;
  }

  .track {
    flex: 1 1 auto;
    min-width: 2rem;
    height: 0.36rem;
    border-radius: 999px;
    background: var(--live-sunken);
    border: 1px solid var(--border);
    overflow: hidden;
  }

  .fill {
    height: 100%;
    border-radius: 999px;
    transition: width 0.45s cubic-bezier(0.22, 1, 0.36, 1);
    background: var(--accent);
  }

  .fill.warn {
    background: var(--warn);
  }

  .fill.bad {
    background: var(--bad);
  }

  .num {
    flex: 0 0 auto;
    font-variant-numeric: tabular-nums;
  }

  .pc {
    flex: 0 0 auto;
    width: 2.8rem;
    text-align: right;
    font-variant-numeric: tabular-nums;
  }

  .pc.warn {
    color: var(--warn);
  }

  .pc.bad {
    color: var(--bad);
  }

  @media (max-width: 720px) {
    .meters {
      flex-wrap: wrap;
      gap: 0.35rem 0.7rem;
      padding: 0.4rem 0.7rem 0.45rem;
    }

    .money {
      flex: 1 1 100%;
      justify-content: space-between;
    }

    .rest {
      align-items: flex-end;
    }

    .bars {
      flex: 1 1 100%;
    }

    .tok {
      display: none;
    }
  }

  @media (prefers-reduced-motion: reduce) {
    .fill {
      transition: none;
    }
  }
</style>
