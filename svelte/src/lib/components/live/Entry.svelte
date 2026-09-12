<script>
  import Copy from './Copy.svelte';
  import Icon from './Icon.svelte';
  import Markdown from './Markdown.svelte';

  let { item } = $props();

  function clock(iso) {
    if (!iso) return '';
    const date = new Date(iso);
    return Number.isNaN(+date) ? '' : date.toLocaleTimeString(undefined, { hour12: false });
  }
</script>

{#if item.type === 'step'}
  <div class="divider step">
    <Icon name="step" size={13} />
    <span class="label">Step {item.step}</span>
    <span class="line"></span>
    <time class="muted tiny">{clock(item.at)}</time>
  </div>

{:else if item.type === 'think'}
  {#if item.text && item.text.trim()}
    <article class="entry think">
      <div class="card thought-card">
        <div class="thought-body prose">
          <Markdown source={item.text} streaming={item.streaming} />
        </div>
      </div>
    </article>
  {/if}

{:else if item.type === 'llm'}
  {#if item.thoughts && item.thoughts.trim()}
    <article class="entry think">
      <div class="card thought-card">
        <div class="thought-body prose">
          <Markdown source={item.thoughts} streaming={item.streaming} />
        </div>
      </div>
    </article>
  {/if}
  {#if item.text && item.text.trim()}
    <article class="entry llm direct-code">
      <Markdown source={item.text} streaming={item.streaming} />
    </article>
  {/if}

{:else if item.type === 'code'}
  {#if item.output || item.error}
    {@const isBad = Boolean(item.error) || item.status === 'failed' || (item.exit_code !== null && item.exit_code !== 0)}
    <article class="entry code">
      <div class="card output-card" class:ok-border={!isBad} class:bad-border={isBad}>
        {#if item.output}
          <div class="terminal-wrap">
            <div class="tools"><Copy text={item.output} label="Copy Output" /></div>
            <pre class="terminal">{item.output}</pre>
          </div>
        {/if}
        {#if item.error}
          <div class="error-box">{item.error}</div>
        {/if}
      </div>
    </article>
  {/if}

{:else if item.type === 'text' || item.type === 'reply'}
  <article class="entry {item.type} direct-code">
    <Markdown source={item.text} streaming={item.streaming} />
  </article>

{:else if item.type === 'prompt'}
  <article class="entry prompt">
    <div class="card prompt-card">
      <pre class="source">{item.text}</pre>
    </div>
  </article>

{:else if item.type === 'note'}
  {#if item.attributes}
    <article class="entry note">
      <div class="card">
        <pre class="source">{JSON.stringify(item.attributes, null, 2)}</pre>
      </div>
    </article>
  {/if}

{:else if item.type === 'error'}
  <article class="entry error bad">
    <div class="card error-box bad-border">
      <strong>Error:</strong> {item.message || item.text}
    </div>
  </article>
{/if}

<style>
  .divider {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    margin: 1.2rem 0 0.5rem;
    color: var(--muted);
  }
  .divider .label {
    font-size: 0.78rem;
    font-weight: 600;
    letter-spacing: 0.04em;
    text-transform: uppercase;
    color: var(--text);
  }
  .divider .line {
    flex: 1;
    min-width: 1rem;
    height: 1px;
    background: var(--border);
  }

  .entry {
    display: block;
    margin: 0.45rem 0;
    width: 100%;
  }

  .direct-code {
    width: 100%;
  }
  .direct-code :global(pre) {
    margin: 0;
  }

  .card {
    border: 1px solid var(--border);
    border-radius: 8px;
    background: var(--panel);
    overflow: hidden;
    min-width: 0;
  }

  .ok-border {
    border: 1.5px solid var(--ok) !important;
  }
  .bad-border {
    border: 1.5px solid var(--bad) !important;
  }

  .thought-card {
    border-left: 3px solid var(--live-think, #8250df);
    background: color-mix(in srgb, var(--live-think, #8250df) 3%, var(--panel));
  }

  .thought-body {
    padding: 0.6rem 0.85rem;
    font-size: 0.9rem;
    line-height: 1.6;
    color: var(--text);
  }

  .prompt-card {
    border-left: 3px solid var(--accent);
    background: color-mix(in srgb, var(--accent) 3%, var(--panel));
  }

  .output-card {
    background: var(--live-sunken);
  }

  .terminal-wrap {
    position: relative;
  }

  .terminal-wrap .tools {
    position: absolute;
    top: 0.35rem;
    right: 0.35rem;
    opacity: 0;
    transition: opacity 0.12s ease;
  }

  .terminal-wrap:hover .tools,
  .terminal-wrap .tools:focus-within {
    opacity: 1;
  }

  @media (hover: none) {
    .terminal-wrap .tools {
      opacity: 1;
    }
  }

  pre.source {
    margin: 0;
    padding: 0.65rem 0.85rem;
    background: transparent;
    font-size: 0.84rem;
    font-family: var(--mono);
    line-height: 1.5;
    overflow-x: auto;
    white-space: pre-wrap;
    word-break: break-word;
  }

  pre.terminal {
    margin: 0;
    padding: 0.65rem 0.85rem;
    background: var(--live-sunken);
    color: var(--text);
    font-size: 0.82rem;
    font-family: var(--mono);
    line-height: 1.5;
    overflow-x: auto;
    white-space: pre-wrap;
    max-height: 32rem;
  }

  .error-box {
    padding: 0.55rem 0.85rem;
    color: var(--bad);
    font-size: 0.84rem;
    background: color-mix(in srgb, var(--bad) 10%, transparent);
    white-space: pre-wrap;
  }

  .prose {
    padding: 0.5rem 0.8rem;
    font-size: 0.9rem;
    line-height: 1.55;
  }

  .tiny { font-size: 0.73rem; }
  .mono { font-family: var(--mono); }
</style>
