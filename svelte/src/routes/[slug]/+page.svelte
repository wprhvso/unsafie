<script>
  import { onMount, tick } from 'svelte';

  import 'github-markdown-css/github-markdown.css';
  import 'katex/dist/katex.min.css';
  import '$lib/highlight.css';

  import { plain, render } from '$lib/markdown.js';
  import { zoomable } from '$lib/zoom.js';

  // The pinch is ours, so the browser must keep its hands off it.
  const VIEWPORT = 'width=device-width, initial-scale=1, maximum-scale=1, user-scalable=no';

  let view = $state('loading');
  let article = $state(null);

  function payload() {
    const el = document.getElementById('payload');
    if (!el) return null;
    try {
      return JSON.parse(el.textContent);
    } catch {
      return null;
    }
  }

  function viewport() {
    const meta = document.querySelector('meta[name="viewport"]');
    if (!meta) return () => {};
    const previous = meta.getAttribute('content');
    meta.setAttribute('content', VIEWPORT);
    return () => meta.setAttribute('content', previous ?? '');
  }

  onMount(() => {
    const restoreViewport = viewport();
    const stopZoom = zoomable();

    (async () => {
      const data = payload();
      const source = typeof data?.content === 'string' ? data.content : null;
      if (!source) {
        view = 'missing';
        return;
      }
      let content;
      try {
        content = await render(source);
      } catch (error) {
        console.error('render failed', error);
        content = plain(source);
      }
      view = 'answer';
      await tick();
      article?.replaceChildren(...content.childNodes);
    })();

    return () => {
      stopZoom();
      restoreViewport();
    };
  });
</script>

<svelte:head>
  <title>unsafie</title>
  <meta name="color-scheme" content="light dark" />
  <link rel="icon" href="data:," />
</svelte:head>

<main>
  {#if view === 'loading'}
    <p class="muted">Loading…</p>
  {:else if view === 'answer'}
    <article bind:this={article} class="markdown-body"></article>
  {:else}
    <p class="muted">This link does not exist or has been removed.</p>
    <p class="small"><a href="/admin">Go to the admin panel</a></p>
  {/if}
</main>

<style>
  :global(:root) {
    color-scheme: light dark;
    --answer-zoom: 1;
    --copy-fg: #656d76;
    --copy-fg-hover: #1f2328;
    --copy-bg: #f6f8fa;
    --copy-bg-hover: #eff2f5;
    --copy-border: #d1d9e0;
    --copy-ok: #1a7f37;
  }

  :global(html),
  :global(body) {
    background: #ffffff;
    -webkit-text-size-adjust: none;
  }

  @media (prefers-color-scheme: dark) {
    :global(:root) {
      --copy-fg: #9198a1;
      --copy-fg-hover: #f0f6fc;
      --copy-bg: #161b22;
      --copy-bg-hover: #21262d;
      --copy-border: #3d444d;
      --copy-ok: #3fb950;
    }

    :global(html),
    :global(body) {
      background: #0d1117;
    }
  }

  main {
    box-sizing: border-box;
    width: 100%;
    max-width: calc(44rem / var(--answer-zoom));
    margin: 0 auto;
    padding: calc(2rem / var(--answer-zoom)) calc(1.25rem / var(--answer-zoom))
      calc(4rem / var(--answer-zoom));
    zoom: var(--answer-zoom);
  }

  .markdown-body {
    background: transparent;
    overflow-wrap: anywhere;
  }

  :global(.markdown-body > :first-child) {
    margin-top: 0;
  }

  :global(.markdown-body pre) {
    overflow-x: auto;
  }

  :global(.markdown-body pre code.hljs) {
    padding: 0;
    background: transparent;
  }

  :global(.katex-display) {
    overflow-x: auto;
    overflow-y: hidden;
    padding: 0.25em 0;
  }

  :global(.code-block) {
    position: relative;
  }

  :global(.code-copy) {
    position: absolute;
    top: 8px;
    right: 8px;
    display: flex;
    align-items: center;
    justify-content: center;
    width: 28px;
    height: 28px;
    padding: 0;
    border: 1px solid var(--copy-border);
    border-radius: 6px;
    background: var(--copy-bg);
    color: var(--copy-fg);
    cursor: pointer;
    opacity: 0;
    transition: opacity 0.1s ease-in-out;
  }

  :global(.code-block:hover .code-copy),
  :global(.code-copy:focus-visible) {
    opacity: 1;
  }

  :global(.code-copy:hover) {
    background: var(--copy-bg-hover);
    color: var(--copy-fg-hover);
  }

  :global(.code-copy.copied) {
    opacity: 1;
    color: var(--copy-ok);
  }

  :global(.code-copy svg) {
    display: block;
    width: 16px;
    height: 16px;
    fill: currentColor;
  }

  :global(.code-copy .icon-check) {
    display: none;
  }

  :global(.code-copy.copied .icon-copy) {
    display: none;
  }

  :global(.code-copy.copied .icon-check) {
    display: block;
  }

  @media (hover: none) {
    :global(.code-copy) {
      opacity: 1;
    }
  }
</style>
