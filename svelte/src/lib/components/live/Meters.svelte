<script>
  import { onMount } from 'svelte';

  let { cost = 0, budget = null, context = 0, limit = 200000, tokens = 0, live = false } = $props();

  const EASE = 0.18;
  const EPS = 0.00002;

  let shown = $state(0);
  let bumped = $state(false);
  let frame;
  let bump;

  onMount(() => {
    const tick = () => {
      const gap = cost - shown;
      if (Math.abs(gap) < EPS) shown = cost;
      else shown += gap * EASE;
      frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => {
      cancelAnimationFrame(frame);
      clearTimeout(bump);
    };
  });

  $effect(() => {
    void cost;
    bumped = true;
    clearTimeout(bump);
    bump = setTimeout(() => (bumped = false), 700);
  });

  const pct = (value, max) => (max > 0 ? Math.min(100, Math.max(0, (value / max) * 100)) : 0);

  const contextPct = $derived(pct(context, limit));
  const budgetPct = $derived(budget ? pct(cost, budget) : 0);
  const left = $derived(budget === null ? null : Math.max(budget - cost, 0));

  const tone = (value) => (value >= 90 ? 'bad' : value >= 70 ? 'warn' : 'ok');

  const compact = (n) =>
    n >= 1000 ? `${(n / 1000).toFixed(n >= 10000 ? 0 : 1)}k` : String(Math.round(n));

  const money = (value, digits = 4) => `$${Number(value ?? 0).toFixed(digits)}`;
</script>

<section class="meters" class:live>
  <div class="cost" class:bumped title="spent on this turn, exactly as charged">
    <span class="label">spent</span>
    <span class="value mono">{money(shown)}</span>
    {#if live}<span class="pulse" aria-hidden="true"></span>{/if}
  </div>

  <div class="bar-box" title="context window filled">
    <div class="head">
      <span class="label">context</span>
      <span class="mono num">{compact(context)} / {compact(limit)}</span>
      <span class="mono pc {tone(contextPct)}">{contextPct.toFixed(1)}%</span>
    </div>
    <div class="track" role="progressbar" aria-valuenow={Math.round(contextPct)} aria-valuemin="0" aria-valuemax="100">
      <div class="fill {tone(contextPct)}" style="width:{contextPct}%"></div>
    </div>
  </div>

  <div class="bar-box" title="turn budget">
    <div class="head">
      <span class="label">budget</span>
      <span class="mono num">{budget === null ? '—' : `${money(cost)} / ${money(budget, 2)}`}</span>
      <span class="mono pc {tone(budgetPct)}">{budget === null ? '' : `${budgetPct.toFixed(1)}%`}</span>
    </div>
    <div class="track" role="progressbar" aria-valuenow={Math.round(budgetPct)} aria-valuemin="0" aria-valuemax="100">
      <div class="fill {tone(budgetPct)}" style="width:{budgetPct}%"></div>
    </div>
  </div>

  <div class="left" title="left of the budget">
    <span class="label">left</span>
    <span class="value mono">{left === null ? '—' : money(left)}</span>
  </div>

  <div class="tokens" title="tokens used in total">
    <span class="label">tokens</span>
    <span class="value mono">{tokens.toLocaleString()}</span>
  </div>
</section>

<style>
  .meters {
    display: grid;
    grid-template-columns: auto 1fr 1fr auto auto;
    align-items: center;
    gap: 0 1rem;
    padding: 0.45rem 0.9rem 0.55rem;
    border-bottom: 1px solid var(--border);
    background: var(--live-bar);
    backdrop-filter: saturate(140%) blur(10px);
  }

  .label {
    font-size: 0.64rem;
    letter-spacing: 0.06em;
    text-transform: uppercase;
    color: var(--muted);
  }

  .cost,
  .left,
  .tokens {
    display: flex;
    flex-direction: column;
    gap: 0.1rem;
    position: relative;
  }

  .value {
    font-variant-numeric: tabular-nums;
    font-size: 0.95rem;
    font-weight: 600;
    line-height: 1.1;
  }

  .cost .value {
    font-size: 1.25rem;
    letter-spacing: -0.01em;
  }

  .cost.bumped .value {
    color: var(--accent);
    transition: color 0.5s ease;
  }

  .pulse {
    position: absolute;
    right: -0.6rem;
    top: 0.9rem;
    width: 0.4rem;
    height: 0.4rem;
    border-radius: 50%;
    background: var(--accent);
    animation: beat 1.4s ease-in-out infinite;
  }

  .bar-box {
    display: flex;
    flex-direction: column;
    gap: 0.25rem;
    min-width: 8rem;
  }

  .head {
    display: flex;
    align-items: baseline;
    gap: 0.4rem;
    font-size: 0.72rem;
    color: var(--muted);
  }

  .head .num {
    margin-left: auto;
    font-variant-numeric: tabular-nums;
  }

  .head .pc {
    font-variant-numeric: tabular-nums;
    min-width: 3.2rem;
    text-align: right;
  }

  .pc.ok { color: var(--ok); }
  .pc.warn { color: var(--warn); }
  .pc.bad { color: var(--bad); }

  .track {
    height: 0.42rem;
    border-radius: 999px;
    background: var(--live-sunken);
    border: 1px solid var(--border);
    overflow: hidden;
  }

  .fill {
    height: 100%;
    border-radius: 999px;
    transition: width 0.45s cubic-bezier(0.22, 1, 0.36, 1);
    background: linear-gradient(90deg, var(--accent), var(--ok));
  }

  .fill.warn { background: linear-gradient(90deg, var(--accent), var(--warn)); }
  .fill.bad { background: linear-gradient(90deg, var(--warn), var(--bad)); }

  @keyframes beat {
    50% { opacity: 0.2; }
  }

  @media (max-width: 720px) {
    .meters {
      grid-template-columns: auto 1fr;
      gap: 0.5rem 0.8rem;
    }

    .tokens { display: none; }
  }

  @media (prefers-reduced-motion: reduce) {
    .pulse { animation: none; }
    .fill { transition: none; }
  }
</style>
