<script>
  import { onMount } from 'svelte';
  import { marked } from 'marked';

  let payload = $state(null);
  let html = $state('');
  let ready = $state(false);

  onMount(() => {
    const el = document.getElementById('payload');
    if (el) {
      try {
        payload = JSON.parse(el.textContent);
      } catch {
        payload = null;
      }
    }
    if (payload?.content) {
      marked.setOptions({ breaks: true, gfm: true });
      html = marked.parse(payload.content);
    }
    ready = true;
  });
</script>

<svelte:head><title>unsafie</title></svelte:head>

<main>
  {#if !ready}
    <p class="muted">Loading…</p>
  {:else if payload?.content}
    <article>{@html html}</article>
  {:else}
    <p class="muted">This link does not exist or has been removed.</p>
    <p class="small"><a href="/admin">Go to the admin panel</a></p>
  {/if}
</main>

<style>
  main { max-width: 46rem; margin: 0 auto; padding: 2rem 1rem 5rem; }
  article :global(h1) { font-size: 1.5rem; }
  article :global(h2) { font-size: 1.2rem; margin-top: 1.6rem; }
  article :global(pre) { margin: 1rem 0; }
  article :global(code) { background: var(--panel); padding: .1em .3em; border-radius: 4px; }
  article :global(pre code) { background: none; padding: 0; }
  article :global(blockquote) {
    margin: 1rem 0;
    padding-left: .9rem;
    border-left: 3px solid var(--border);
    color: var(--muted);
  }
  article :global(table) { margin: 1rem 0; }
  article :global(img) { max-width: 100%; border-radius: var(--radius); }
</style>
