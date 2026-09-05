<script>
  let { value, open = false } = $props();
  let shown = $state(open);
</script>

<button class="toggle" onclick={() => (shown = !shown)}>{shown ? '▾' : '▸'} json</button>
{#if shown}
  <pre>{JSON.stringify(value, null, 2)}</pre>
{/if}

<style>
  .toggle { border: 0; background: none; padding: 0; color: var(--muted); font-size: .82rem; }
  pre { margin: .4rem 0 0; max-height: 26rem; }
</style>
