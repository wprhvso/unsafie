<script>
  let { tone = '', children } = $props();
</script>

<span class="badge {tone}">{@render children?.()}</span>

<style>
  .badge {
    display: inline-block;
    padding: .05rem .4rem;
    border-radius: 4px;
    font-size: .8rem;
    border: 1px solid var(--border);
    color: var(--muted);
    white-space: nowrap;
  }
  .ok { color: var(--ok); border-color: color-mix(in srgb, var(--ok) 40%, transparent); }
  .bad { color: var(--bad); border-color: color-mix(in srgb, var(--bad) 40%, transparent); }
  .warn { color: var(--warn); border-color: color-mix(in srgb, var(--warn) 40%, transparent); }
</style>
