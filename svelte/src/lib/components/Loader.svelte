<script>
  let { state, empty = 'Nothing here yet.', children } = $props();
</script>

{#if state.loading && !state.data}
  <p class="muted pad">Loading…</p>
{:else if state.error}
  <p class="pad bad">{state.error}</p>
{:else if state.empty}
  <p class="muted pad">{empty}</p>
{:else}
  {@render children?.()}
{/if}

<style>
  .pad { padding: 1rem; margin: 0; }
  .bad { color: var(--bad); }
</style>
