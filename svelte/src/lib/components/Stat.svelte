<script>
  let { label, value, hint = '', tone = '' } = $props();
</script>

<div class="stat">
  <div class="label">{label}</div>
  <div class="value {tone}">{value}</div>
  {#if hint}<div class="hint muted small">{hint}</div>{/if}
</div>

<style>
  .stat {
    background: var(--panel);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    padding: .7rem .9rem;
  }
  .label { color: var(--muted); font-size: .78rem; text-transform: uppercase; letter-spacing: .04em; }
  .value { font-size: 1.4rem; font-weight: 600; margin-top: .15rem; }
  .value.bad { color: var(--bad); }
  .value.warn { color: var(--warn); }
  .value.ok { color: var(--ok); }
  .hint { margin-top: .1rem; }
</style>
