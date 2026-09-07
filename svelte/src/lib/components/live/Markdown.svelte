<script>
  import { plain, render } from '$lib/markdown.js';

  let { source = '', streaming = false } = $props();

  let host = $state(null);

  $effect(() => {
    const text = source;
    const node = host;
    if (streaming || !node) return;
    let dropped = false;
    (async () => {
      let holder;
      try {
        holder = await render(text);
      } catch {
        holder = plain(text);
      }
      if (!dropped && node.isConnected) node.replaceChildren(...holder.childNodes);
    })();
    return () => {
      dropped = true;
    };
  });
</script>

{#if streaming}
  <div class="raw">{source}<span class="caret"></span></div>
{:else}
  <div bind:this={host} class="markdown-body"></div>
{/if}

<style>
  .raw {
    white-space: pre-wrap;
    overflow-wrap: anywhere;
  }

  .caret {
    display: inline-block;
    width: 0.5em;
    height: 1em;
    margin-left: 0.1em;
    vertical-align: text-bottom;
    background: currentColor;
    opacity: 0.6;
    animation: blink 1s steps(2, start) infinite;
  }

  @keyframes blink {
    to {
      visibility: hidden;
    }
  }

  .markdown-body {
    background: transparent;
    color: inherit;
    font-size: inherit;
    overflow-wrap: anywhere;
  }

  @media (prefers-reduced-motion: reduce) {
    .caret {
      animation: none;
    }
  }
</style>
