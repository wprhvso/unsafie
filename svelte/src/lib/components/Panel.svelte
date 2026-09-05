<script>
  let { title = '', actions, children } = $props();
</script>

<section>
  {#if title || actions}
    <header class="spread">
      <h2>{title}</h2>
      {#if actions}<div class="row">{@render actions()}</div>{/if}
    </header>
  {/if}
  <div class="body">{@render children?.()}</div>
</section>

<style>
  section {
    background: var(--panel);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    overflow: hidden;
  }
  header {
    padding: .7rem 1rem;
    border-bottom: 1px solid var(--border);
  }
  header :global(h2) { margin: 0; }
  .body { overflow-x: auto; }
</style>
