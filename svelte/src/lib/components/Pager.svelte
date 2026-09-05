<script>
  let { total = 0, offset = 0, limit = 50, onmove } = $props();
  const last = $derived(Math.max(0, Math.floor((total - 1) / limit) * limit));
</script>

{#if total > limit}
  <div class="row pager">
    <button disabled={offset === 0} onclick={() => onmove(0)}>«</button>
    <button disabled={offset === 0} onclick={() => onmove(Math.max(0, offset - limit))}>‹</button>
    <span class="muted small nowrap">{offset + 1}–{Math.min(offset + limit, total)} of {total}</span>
    <button disabled={offset + limit >= total} onclick={() => onmove(offset + limit)}>›</button>
    <button disabled={offset + limit >= total} onclick={() => onmove(last)}>»</button>
  </div>
{:else if total}
  <span class="muted small">{total} total</span>
{/if}

<style>
  .pager { padding: .6rem 1rem; border-top: 1px solid var(--border); }
</style>
