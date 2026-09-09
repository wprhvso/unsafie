<script>
  import { short } from '$lib/format.js';
  import Copy from './Copy.svelte';
  import Icon from './Icon.svelte';
  import Markdown from './Markdown.svelte';

  let { item, open = false, ontoggle } = $props();

  const toggle = () => ontoggle?.(item.id);

  function clock(iso) {
    if (!iso) return '';
    const date = new Date(iso);
    return Number.isNaN(+date) ? '' : date.toLocaleTimeString(undefined, { hour12: false });
  }

  function took(seconds) {
    if (seconds === null || seconds === undefined) return '';
    return seconds < 1 ? `${Math.round(seconds * 1000)} ms` : `${Number(seconds).toFixed(2)} s`;
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
    <article class="entry think" class:open class:busy={item.streaming}>
      <div class="rail">
        <span class="bead"><Icon name="think" size={12} /></span>
      </div>
      <div class="card">
        <button class="head" onclick={toggle} aria-expanded={open}>
          <span class="caret" class:open>▸</span>
          <span class="title">Reasoning</span>
          <span class="spacer"></span>
          <span class="muted tiny nowrap">{item.text?.length?.toLocaleString() ?? 0} chars</span>
          <time class="muted tiny nowrap">{clock(item.at)}</time>
        </button>

        <div class="thought" class:clamped={!open}>
          {item.text}
        </div>

        {#if item.signature && open}
          <div class="signature-bar">
            <span class="muted tiny">Signature:</span>
            <code class="sig-preview" title={item.signature}>{item.signature.slice(0, 32)}…</code>
            <Copy text={item.signature} label="Copy Thought Signature" />
          </div>
        {/if}
      </div>
    </article>
  {/if}

{:else if item.type === 'llm'}
  <article class="entry llm" class:open class:busy={item.streaming}>
    <div class="rail">
      <span class="bead llm-bead"><Icon name="think" size={12} /></span>
    </div>
    <div class="card">
      <button class="head" onclick={toggle} aria-expanded={open}>
        <span class="caret" class:open>▸</span>
        <span class="title mono">LLM: {item.model || 'gemini-flash-latest'}</span>
        <span class="spacer"></span>
        <span class="status-tag {item.streaming ? 'running' : 'ok'}">{item.streaming ? 'streaming…' : 'done'}</span>
        <time class="muted tiny nowrap">{clock(item.at)}</time>
      </button>

      {#if item.thoughts && item.thoughts.trim()}
        <div class="thought" class:clamped={!open}>
          <span class="muted tiny">Reasoning:</span>
          {item.thoughts}
        </div>
      {/if}

      {#if item.text && item.text.trim()}
        <div class="prose" style="padding: 0.5rem 0.75rem;">
          <Markdown source={item.text} streaming={item.streaming} />
        </div>
      {/if}
    </div>
  </article>

{:else if item.type === 'code'}
  <article class="entry code {item.status}" class:open>
    <div class="rail">
      <span class="bead code-bead"><Icon name="code" size={13} /></span>
    </div>

    <div class="card">
      <button class="head" onclick={toggle} aria-expanded={open}>
        <span class="caret" class:open>▸</span>
        <span class="title mono">Bash</span>
        <span class="spacer"></span>
        <span class="status-tag {item.status}">
          {item.status === 'running' ? 'running…' : item.status === 'ok' ? 'ok' : `exit ${item.exit_code ?? 1}`}
        </span>
        {#if item.seconds !== null}
          <span class="muted tiny nowrap">{took(item.seconds)}</span>
        {/if}
        <time class="muted tiny nowrap">{clock(item.at)}</time>
      </button>

      {#if item.output || item.error || item.images?.length}
        <div class="output-box">
          {#if item.output}
            <div class="terminal-wrap">
              <div class="tools"><Copy text={item.output} label="Copy Output" /></div>
              <pre class="terminal">{item.output}</pre>
            </div>
          {/if}

          {#if item.error}
            <div class="error-box">{item.error}</div>
          {/if}

          {#if item.images?.length}
            <div class="images-grid">
              {#each item.images as img}
                <img src="data:{img.media_type || 'image/png'};base64,{img.data}" alt="Output plot" />
              {/each}
            </div>
          {/if}
        </div>
      {/if}
    </div>
  </article>

{:else if item.type === 'text' || item.type === 'reply'}
  <article class="entry {item.type}" class:open>
    <div class="rail">
      <span class="bead"><Icon name={item.type === 'reply' ? 'reply' : 'text'} size={12} /></span>
    </div>
    <div class="card">
      <button class="head" onclick={toggle} aria-expanded={open}>
        <span class="caret" class:open>▸</span>
        <span class="title">{item.type === 'reply' ? 'Sent to chat' : 'Model Output'}</span>
        <span class="spacer"></span>
        <time class="muted tiny nowrap">{clock(item.at)}</time>
      </button>
      <div class="prose">
        <Markdown source={item.text} streaming={item.streaming} />
      </div>
      {#if open && item.type === 'reply' && item.messageIds?.length}
        <div class="details">
          <p class="muted tiny">Telegram message IDs: {item.messageIds.join(', ')}</p>
        </div>
      {/if}
    </div>
  </article>

{:else if item.type === 'prompt'}
  <article class="entry prompt" class:open>
    <div class="rail"><span class="bead"><Icon name="prompt" size={12} /></span></div>
    <div class="card">
      <button class="head" onclick={toggle} aria-expanded={open}>
        <span class="caret" class:open>▸</span>
        <span class="title">User Prompt</span>
        <span class="sub">{short(item.text, 80)}</span>
        <span class="spacer"></span>
        <time class="muted tiny nowrap">{clock(item.at)}</time>
      </button>
      {#if open}
        <div class="body">
          <pre class="source">{item.text}</pre>
        </div>
      {/if}
    </div>
  </article>

{:else if item.type === 'note'}
  <article class="entry note" class:open>
    <div class="rail"><span class="bead"><Icon name="note" size={12} /></span></div>
    <div class="card">
      <button class="head" onclick={toggle} aria-expanded={open}>
        <span class="caret" class:open>▸</span>
        <span class="title">{item.name === 'unsafie.messages_injected' ? 'Injected' : `Note: ${item.name}`}</span>
        <span class="spacer"></span>
        <time class="muted tiny nowrap">{clock(item.at)}</time>
      </button>
      {#if open && item.attributes}
        <div class="body">
          <pre class="source">{JSON.stringify(item.attributes, null, 2)}</pre>
        </div>
      {/if}
    </div>
  </article>

{:else if item.type === 'error'}
  <article class="entry error bad open">
    <div class="rail"><span class="bead"><Icon name="error" size={12} /></span></div>
    <div class="card">
      <div class="head">
        <span class="title">Error</span>
        <span class="spacer"></span>
        <time class="muted tiny nowrap">{clock(item.at)}</time>
      </div>
      <div class="body error-box">{item.message}</div>
    </div>
  </article>

{:else if item.type === 'end'}
  <article class="entry end {item.status === 'ok' ? 'ok' : 'bad'}">
    <div class="rail"><span class="bead"><Icon name="end" size={12} /></span></div>
    <div class="card">
      <div class="head">
        <span class="title">Finished: {item.status}</span>
        <span class="spacer"></span>
        <time class="muted tiny nowrap">{clock(item.at)}</time>
      </div>
      <div class="body">
        <p class="small">{item.steps ?? 0} steps</p>
        {#if item.note}<pre class="source">{item.note}</pre>{/if}
      </div>
    </div>
  </article>
{/if}

<style>
  .divider {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    margin: 1rem 0 0.4rem;
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
  .chip {
    padding: 0.05rem 0.4rem;
    border: 1px solid var(--border);
    border-radius: 999px;
    font-size: 0.72rem;
    background: var(--panel);
  }

  .entry {
    display: grid;
    grid-template-columns: 1.6rem 1fr;
    gap: 0.5rem;
    margin: 0.4rem 0;
  }
  .rail {
    position: relative;
    display: flex;
    justify-content: center;
  }
  .rail::before {
    content: '';
    position: absolute;
    top: 0;
    bottom: -0.6rem;
    width: 1px;
    background: var(--border);
  }
  .bead {
    position: relative;
    display: flex;
    align-items: center;
    justify-content: center;
    width: 1.35rem;
    height: 1.35rem;
    margin-top: 0.35rem;
    border: 1px solid var(--border);
    border-radius: 50%;
    background: var(--bg);
    color: var(--muted);
  }

  .entry.code .code-bead {
    color: var(--accent);
    border-color: color-mix(in srgb, var(--accent) 45%, var(--border));
  }
  .entry.llm .llm-bead {
    color: var(--live-think, #8250df);
    border-color: color-mix(in srgb, var(--live-think, #8250df) 45%, var(--border));
  }
  .entry.think .bead {
    color: var(--live-think, #8250df);
    border-color: color-mix(in srgb, var(--live-think, #8250df) 45%, var(--border));
  }
  .entry.reply .bead {
    color: var(--ok);
    border-color: color-mix(in srgb, var(--ok) 45%, var(--border));
  }
  .entry.error .bead,
  .entry.bad .bead {
    color: var(--bad);
    border-color: color-mix(in srgb, var(--bad) 45%, var(--border));
  }

  .entry.busy .bead {
    animation: pulse 1.4s ease-in-out infinite;
  }
  @keyframes pulse {
    50% { box-shadow: 0 0 0 4px color-mix(in srgb, var(--accent) 14%, transparent); }
  }

  .card {
    border: 1px solid var(--border);
    border-radius: 8px;
    background: var(--panel);
    overflow: hidden;
    min-width: 0;
  }
  .entry.open .card,
  .card:hover {
    border-color: color-mix(in srgb, var(--accent) 35%, var(--border));
  }

  .head {
    display: flex;
    align-items: center;
    gap: 0.45rem;
    width: 100%;
    padding: 0.45rem 0.6rem;
    border: 0;
    background: none;
    color: inherit;
    text-align: left;
    cursor: pointer;
    min-width: 0;
  }
  .head:hover {
    background: color-mix(in srgb, var(--accent) 5%, transparent);
  }
  .caret {
    color: var(--muted);
    font-size: 0.7rem;
    transition: transform 0.12s ease;
  }
  .caret.open {
    transform: rotate(90deg);
  }
  .title {
    font-weight: 600;
    font-size: 0.88rem;
    flex: 0 0 auto;
  }
  .sub {
    color: var(--muted);
    font-size: 0.82rem;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    min-width: 0;
  }
  .spacer {
    flex: 1;
    min-width: 0.3rem;
  }

  .status-tag {
    font-size: 0.72rem;
    padding: 0.05rem 0.4rem;
    border-radius: 999px;
    background: color-mix(in srgb, var(--muted) 15%, transparent);
    color: var(--muted);
  }
  .status-tag.ok {
    background: color-mix(in srgb, var(--ok) 16%, transparent);
    color: var(--ok);
  }
  .status-tag.failed {
    background: color-mix(in srgb, var(--bad) 16%, transparent);
    color: var(--bad);
  }
  .status-tag.running {
    background: color-mix(in srgb, var(--warn) 16%, transparent);
    color: var(--warn);
  }

  .signature-bar {
    display: flex;
    align-items: center;
    gap: 0.4rem;
    padding: 0.35rem 0.7rem;
    border-top: 1px dashed var(--border);
    background: var(--live-sunken);
  }
  .sig-preview {
    font-size: 0.75rem;
    color: var(--muted);
    background: none;
    padding: 0;
  }

  .thought {
    padding: 0.4rem 0.7rem 0.6rem;
    font-size: 0.84rem;
    line-height: 1.55;
    color: var(--muted);
    white-space: pre-wrap;
    overflow-wrap: anywhere;
    font-style: italic;
  }
  .thought.clamped {
    display: -webkit-box;
    -webkit-line-clamp: 4;
    line-clamp: 4;
    -webkit-box-orient: vertical;
    overflow: hidden;
  }

  .output-box {
    border-top: 1px solid var(--border);
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
    padding: 0.6rem 0.7rem;
    background: transparent;
    font-size: 0.82rem;
    font-family: var(--mono);
    line-height: 1.5;
    overflow-x: auto;
    white-space: pre;
  }

  pre.terminal {
    margin: 0;
    padding: 0.6rem 0.7rem;
    background: var(--live-sunken);
    color: var(--text);
    font-size: 0.82rem;
    font-family: var(--mono);
    line-height: 1.5;
    overflow-x: auto;
    white-space: pre-wrap;
    max-height: 28rem;
  }

  .error-box {
    padding: 0.5rem 0.7rem;
    color: var(--bad);
    font-size: 0.82rem;
    background: color-mix(in srgb, var(--bad) 10%, transparent);
    white-space: pre-wrap;
  }

  .images-grid {
    display: grid;
    gap: 0.5rem;
    padding: 0.6rem;
    background: var(--live-sunken);
    border-top: 1px solid var(--border);
  }
  .images-grid img {
    max-width: 100%;
    border-radius: 4px;
    border: 1px solid var(--border);
  }

  .prose {
    padding: 0.4rem 0.7rem 0.6rem;
    font-size: 0.9rem;
    line-height: 1.55;
  }
  .body,
  .details {
    padding: 0.5rem 0.7rem;
    border-top: 1px solid var(--border);
  }

  .tiny { font-size: 0.73rem; }
  .small { font-size: 0.85rem; }
  .mono { font-family: var(--mono); }
  .nowrap { white-space: nowrap; }
</style>
