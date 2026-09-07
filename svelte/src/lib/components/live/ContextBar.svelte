<script>
  let { context = 0, limit = 200000 } = $props();

  const filled = $derived(limit > 0 ? Math.min(100, Math.max(0, (context / limit) * 100)) : 0);
  const tone = $derived(filled >= 90 ? 'bad' : filled >= 70 ? 'warn' : '');

  const compact = (n) =>
    n >= 1e6 ? `${(n / 1e6).toFixed(2)}M` : n >= 1000 ? `${Math.round(n / 1000)}k` : String(n);
</script>

<div
  class="meter"
  role="progressbar"
  aria-label="context filled"
  aria-valuenow={Math.round(filled)}
  aria-valuemin="0"
  aria-valuemax="100"
  title="context {compact(context)} of {compact(limit)} · {filled.toFixed(1)}%"
>
  <div class="fill {tone}" style="width:{filled}%"></div>
</div>

<style>
  .meter {
    height: 0.22rem;
    background: var(--live-sunken);
    border-bottom: 1px solid var(--border);
    overflow: hidden;
  }

  .fill {
    height: 100%;
    background: var(--accent);
    transition: width 0.5s cubic-bezier(0.22, 1, 0.36, 1);
  }

  .fill.warn {
    background: var(--warn);
  }

  .fill.bad {
    background: var(--bad);
  }

  @media (prefers-reduced-motion: reduce) {
    .fill {
      transition: none;
    }
  }
</style>
