<script>
  import { bytes } from '$lib/format.js';
  import Copy from './Copy.svelte';

  let { blocks = [] } = $props();

  // base64 inflates by 4/3; close enough to name a size on screen
  const weigh = (n) => bytes(Math.round((n ?? 0) * 0.75));
</script>

{#if !blocks.length}
  <p class="muted small none">Nothing came back.</p>
{/if}

{#each blocks as block, i (i)}
  {#if block.type === 'image' && block.data}
    <figure>
      <img src="data:{block.media_type ?? 'image/png'};base64,{block.data}" alt="tool output" />
      <figcaption class="muted tiny">{block.media_type} · {weigh(block.size)}</figcaption>
    </figure>
  {:else if block.type === 'image'}
    <p class="muted small none">
      {block.media_type ?? 'image'} · {weigh(block.size)} — too large to inline
    </p>
  {:else if block.type === 'text'}
    <div class="text">
      <div class="tools"><Copy text={block.text ?? ''} /></div>
      <pre>{block.text}</pre>
      {#if block.cut}
        <p class="muted tiny cut">+{block.cut.toLocaleString()} more characters not captured</p>
      {/if}
    </div>
  {:else}
    <p class="muted small none">{block.type}</p>
  {/if}
{/each}

<style>
  .none {
    margin: 0.2rem 0;
  }

  .text {
    position: relative;
  }

  .tools {
    position: absolute;
    top: 0.3rem;
    right: 0.3rem;
    opacity: 0;
    transition: opacity 0.12s ease;
  }

  .text:hover .tools,
  .tools:focus-within {
    opacity: 1;
  }

  pre {
    margin: 0.2rem 0;
    padding: 0.6rem 0.7rem;
    background: var(--live-sunken);
    border: 1px solid var(--border);
    border-radius: 6px;
    white-space: pre-wrap;
    overflow-wrap: anywhere;
    max-height: 32rem;
    overflow: auto;
    font-size: 0.82rem;
    line-height: 1.5;
  }

  figure {
    margin: 0.3rem 0;
  }

  img {
    display: block;
    max-width: 100%;
    border: 1px solid var(--border);
    border-radius: 6px;
  }

  .tiny {
    font-size: 0.73rem;
  }

  .cut {
    margin: 0.15rem 0 0;
  }

  @media (hover: none) {
    .tools {
      opacity: 1;
    }
  }
</style>
