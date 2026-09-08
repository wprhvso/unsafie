<script>
  import { UNITS_PER_USD, short } from '$lib/format.js';
  import Copy from './Copy.svelte';
  import Icon from './Icon.svelte';
  import Markdown from './Markdown.svelte';
  import Output from './Output.svelte';
  import Tree from './Tree.svelte';

  let { item, open = false, ontoggle } = $props();

  const NOTABLE_STOP = new Set(['max_tokens', 'refusal', 'model_context_window_exceeded']);

  const TITLES = {
    prompt: 'Request',
    think: 'Reasoning',
    text: 'Assistant',
    reply: 'Sent to the chat',
    note: 'Note',
    error: 'Error',
    end: 'Finished'
  };


  const BLANK = {
    summarized: 'The API returned no summary for this block.',
    updates: 'Empty by design: display = updates returns progress notes, not the reasoning.',
    omitted: 'Empty by design: display = omitted drops the reasoning.',
    off: 'The request carries no thinking.display, so the reasoning comes back empty.'
  };

  const HEADLINE = [
    'path',
    'query',
    'command',
    'url',
    'repo',
    'title',
    'name',
    'text',
    'message',
    'body'
  ];

  function headline(input) {
    if (!input || typeof input !== 'object') return '';
    for (const key of HEADLINE) {
      if (typeof input[key] === 'string' && input[key].trim()) return input[key];
    }
    const first = Object.values(input).find((v) => typeof v === 'string' && v.trim());
    return first ?? '';
  }

  function firstText(blocks) {
    for (const block of blocks ?? []) {
      if (block?.type === 'text' && block.text) return block.text;
    }
    return '';
  }

  function lastLine(text) {
    const lines = String(text ?? '')
      .split('\n')
      .filter((line) => line.trim());
    return lines.length ? lines[lines.length - 1] : '';
  }

  function clock(iso) {
    if (!iso) return '';
    const date = new Date(iso);
    return Number.isNaN(+date) ? '' : date.toLocaleTimeString(undefined, { hour12: false });
  }

  function took(ms) {
    if (ms === null || ms === undefined) return '';
    return ms < 1000 ? `${Math.round(ms)} ms` : `${(ms / 1000).toFixed(ms < 10000 ? 2 : 1)} s`;
  }

  function tokens(usage) {
    if (!usage) return '';
    const parts = [];
    if (usage.input_tokens) parts.push(`in ${usage.input_tokens.toLocaleString()}`);
    if (usage.cache_read_input_tokens)
      parts.push(`cached ${usage.cache_read_input_tokens.toLocaleString()}`);
    if (usage.output_tokens) parts.push(`out ${usage.output_tokens.toLocaleString()}`);
    return parts.join(' · ');
  }

  function decode(text) {
    try {
      const value = JSON.parse(text);
      return value && typeof value === 'object' ? value : null;
    } catch {
      return null;
    }
  }

  const icon = $derived(item.type === 'tool' || item.type === 'raw' ? 'tool' : item.type);
  const title = $derived(
    item.type === 'tool' || item.type === 'raw' ? item.name : (TITLES[item.type] ?? item.type)
  );
  const structured = $derived(item.type === 'prompt' ? decode(item.text) : null);
  const broke = $derived(item.type === 'tool' && item.phase === 'done' && item.ok === false);
  const sub = $derived.by(() => {
    switch (item.type) {
      case 'tool':
        return broke
          ? short(lastLine(firstText(item.output)) || headline(item.input), 90)
          : short(headline(item.input) || item.args, 90);
      case 'error':
        return short(item.message, 90);
      case 'note':
        return item.name;
      case 'prompt':
        return short(structured?.text ?? item.text, 90);
      default:
        return '';
    }
  });
  const sent = $derived(item.display || 'off');
  const wanted = $derived(item.configured || 'off');
  const refused = $derived(wanted !== 'off' && wanted !== sent);
  const blank = $derived(
    refused
      ? `display = ${wanted} is configured, but the API refused it: the request went without it and the block comes back empty.`
      : (BLANK[sent] ?? BLANK.off)
  );
  const mode = $derived(
    item.thinking === 'off' ? 'thinking off' : `thinking ${item.thinking} · display ${sent}`
  );
  const tone = $derived(
    item.type === 'error' || item.ok === false || item.status === 'failed'
      ? 'bad'
      : item.type === 'end' || item.ok === true
        ? 'ok'
        : ''
  );
  const toggle = () => ontoggle?.(item.id);
</script>

{#if item.type === 'step'}
  <div class="divider step">
    <Icon name="step" size={13} />
    <span class="label">Step {item.step}</span>
    {#if NOTABLE_STOP.has(item.stop)}<span class="muted tiny">stop: {item.stop}</span>{/if}
    {#if item.usage}<span class="muted tiny">{tokens(item.usage)}</span>{/if}
    <span class="line"></span>
    <time class="muted tiny">{clock(item.at)}</time>
  </div>
{:else if item.type === 'attempt'}
  <div class="divider attempt">
    <Icon name="attempt" size={13} />
    <span class="label">Attempt {item.attempt}</span>
    {#if item.model}<span class="chip mono">{item.model}</span>{/if}
    {#if item.effort}<span class="chip">effort {item.effort}</span>{/if}
    {#if item.thinking}<span class="chip">{mode}</span>{/if}
    {#if refused}<span class="chip warn">display {wanted} refused</span>{/if}
    {#if item.tools}<span class="muted tiny">{item.tools} tools</span>{/if}
    <span class="line"></span>
    <time class="muted tiny">{clock(item.at)}</time>
  </div>
{:else}
  <article class="entry {item.type} {tone}" class:open class:busy={item.streaming}>
    <div class="rail">
      <span class="bead"><Icon name={icon} size={12} /></span>
    </div>

    <div class="card">
      <button class="head" onclick={toggle} aria-expanded={open}>
        <span class="caret" class:open>▸</span>
        <span class="title" class:mono={item.type === 'tool'}>{title}</span>
        {#if sub}<span class="sub" class:broke>{sub}</span>{/if}
        <span class="spacer"></span>
        {#if item.type === 'tool'}
          <span class="state {item.phase}">
            {item.phase === 'done' ? (item.ok ? 'ok' : 'failed') : item.phase}
          </span>
          {#if item.ms !== null && item.ms !== undefined}
            <span class="muted tiny nowrap">{took(item.ms)}</span>
          {/if}
        {/if}
        {#if item.type === 'think' && item.text}
          <span class="muted tiny nowrap">{item.text.length.toLocaleString()} chars</span>
        {/if}
        <time class="muted tiny nowrap">{clock(item.at)}</time>
      </button>

      {#if item.type === 'think'}
        {#if item.redacted}
          <p class="muted small pad">The model encrypted this block; the API returns no text.</p>
        {:else if item.text}
          <div class="thought" class:clamped={!open}>{item.text}</div>
          {#if open}
            <div class="foot"><Copy text={item.text} label="Copy the reasoning" /></div>
          {/if}
        {:else if item.hidden || !item.streaming}
          <p class="muted small pad">{blank}</p>
        {:else}
          <p class="muted small pad">Thinking…</p>
        {/if}
      {:else if item.type === 'text' || item.type === 'reply'}
        <div class="prose">
          <Markdown source={item.text} streaming={item.streaming} />
        </div>
        {#if open}
          <div class="details">
            {#if item.messageIds?.length}
              <p class="muted tiny">telegram message ids: {item.messageIds.join(', ')}</p>
            {/if}
            {#if item.kind}<p class="muted tiny">kind: {item.kind}</p>{/if}
            <pre class="source">{item.text}</pre>
            <div class="foot"><Copy text={item.text} label="Copy the source" /></div>
          </div>
        {/if}
      {:else if item.type === 'tool' && open}
        <div class="body">
          <div class="section">
            <h4>Input</h4>
            {#if item.input}
              <Tree value={item.input} />
            {:else if item.args}
              <pre class="source">{item.args}</pre>
            {:else}
              <p class="muted small">Arguments are still streaming in…</p>
            {/if}
          </div>
          {#if item.phase === 'done'}
            <div class="section">
              <h4>Output</h4>
              <Output blocks={item.output ?? []} />
            </div>
          {/if}
          <div class="section meta">
            <span class="muted tiny mono">{item.callId ?? '—'}</span>
            <span class="muted tiny">step {item.step}</span>
            {#if item.server}<span class="muted tiny">server tool</span>{/if}
          </div>
        </div>
      {:else if item.type === 'prompt' && open}
        <div class="body">
          {#if structured}
            <Tree value={structured} />
          {:else}
            <pre class="source">{item.text}</pre>
          {/if}
        </div>
      {:else if item.type === 'raw' && open}
        <div class="body">
          {#if item.block}
            <Tree value={item.block} />
          {:else}
            <p class="muted small">The API sent a <code>{item.name}</code> block with no payload.</p>
          {/if}
        </div>
      {:else if item.type === 'note' && open}
        <div class="body">
          {#if item.attributes && Object.keys(item.attributes).length}
            <Tree value={item.attributes} />
          {:else}
            <p class="muted small">No attributes.</p>
          {/if}
        </div>
      {:else if item.type === 'error' && open}
        <div class="body">
          {#if item.errorType}<p class="muted tiny">{item.errorType}</p>{/if}
          <pre class="source">{item.message}</pre>
        </div>
      {:else if item.type === 'end'}
        <div class="body">
          <p class="small">
            {item.status}{item.steps ? ` · ${item.steps} steps` : ''}{item.charge
              ? ` · $${(Number(item.charge) / UNITS_PER_USD).toFixed(4)} charged`
              : ''}{item.cost ? ` · $${Number(item.cost).toFixed(4)} api` : ''}
          </p>
          {#if item.note}<pre class="source">{item.note}</pre>{/if}
        </div>
      {/if}
    </div>
  </article>
{/if}

<style>
  .divider {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    margin: 1.1rem 0 0.5rem;
    color: var(--muted);
    flex-wrap: wrap;
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

  .divider.attempt .label {
    color: var(--warn);
  }

  .chip {
    padding: 0.05rem 0.4rem;
    border: 1px solid var(--border);
    border-radius: 999px;
    font-size: 0.72rem;
    background: var(--panel);
  }

  .chip.warn {
    color: var(--warn);
    border-color: color-mix(in srgb, var(--warn) 45%, var(--border));
  }

  .entry {
    display: grid;
    grid-template-columns: 1.6rem 1fr;
    gap: 0.5rem;
    margin: 0.3rem 0;
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

  .entry.think .bead {
    color: var(--live-think);
    border-color: color-mix(in srgb, var(--live-think) 45%, var(--border));
  }

  .entry.tool .bead {
    color: var(--accent);
    border-color: color-mix(in srgb, var(--accent) 45%, var(--border));
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
    50% {
      box-shadow: 0 0 0 4px color-mix(in srgb, var(--accent) 14%, transparent);
    }
  }

  .card {
    border: 1px solid var(--border);
    border-radius: 10px;
    background: var(--panel);
    overflow: hidden;
    min-width: 0;
    transition: border-color 0.12s ease;
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
    border-radius: 0;
    background: none;
    color: inherit;
    text-align: left;
    cursor: pointer;
    min-width: 0;
  }

  .head:hover {
    background: color-mix(in srgb, var(--accent) 5%, transparent);
    color: inherit;
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

  .sub.broke {
    color: var(--bad);
  }

  .spacer {
    flex: 1;
    min-width: 0.3rem;
  }

  .state {
    font-size: 0.72rem;
    padding: 0.05rem 0.4rem;
    border-radius: 999px;
    background: color-mix(in srgb, var(--muted) 15%, transparent);
    color: var(--muted);
    flex: 0 0 auto;
  }

  .state.running,
  .state.writing {
    background: color-mix(in srgb, var(--accent) 16%, transparent);
    color: var(--accent);
  }

  .entry.ok .state.done {
    background: color-mix(in srgb, var(--ok) 16%, transparent);
    color: var(--ok);
  }

  .entry.bad .state.done {
    background: color-mix(in srgb, var(--bad) 16%, transparent);
    color: var(--bad);
  }

  .thought {
    padding: 0 0.7rem 0.6rem;
    font-size: 0.84rem;
    line-height: 1.55;
    color: var(--muted);
    white-space: pre-wrap;
    overflow-wrap: anywhere;
    font-style: italic;
  }

  .thought.clamped {
    display: -webkit-box;
    -webkit-line-clamp: 5;
    line-clamp: 5;
    -webkit-box-orient: vertical;
    overflow: hidden;
  }

  .prose {
    padding: 0 0.7rem 0.6rem;
    font-size: 0.9rem;
    line-height: 1.55;
  }

  .body,
  .details {
    padding: 0.1rem 0.7rem 0.7rem;
    border-top: 1px solid var(--border);
    margin-top: 0.1rem;
  }

  .section + .section {
    margin-top: 0.7rem;
  }

  h4 {
    margin: 0.5rem 0 0.3rem;
    font-size: 0.72rem;
    letter-spacing: 0.05em;
    text-transform: uppercase;
    color: var(--muted);
    font-weight: 600;
  }

  .meta {
    display: flex;
    gap: 0.7rem;
    flex-wrap: wrap;
    padding-top: 0.4rem;
    border-top: 1px dashed var(--border);
  }

  .source {
    margin: 0.2rem 0;
    padding: 0.6rem 0.7rem;
    background: var(--live-sunken);
    border: 1px solid var(--border);
    border-radius: 6px;
    white-space: pre-wrap;
    overflow-wrap: anywhere;
    max-height: 26rem;
    overflow: auto;
    font-size: 0.8rem;
  }

  .pad {
    padding: 0 0.7rem 0.6rem;
    margin: 0;
  }

  .foot {
    display: flex;
    justify-content: flex-end;
    padding: 0 0.7rem 0.5rem;
  }

  .tiny {
    font-size: 0.73rem;
  }

  code {
    padding: 0.05rem 0.25rem;
    border-radius: 4px;
    background: var(--live-sunken);
  }

  @media (prefers-reduced-motion: reduce) {
    .entry.busy .bead {
      animation: none;
    }
  }
</style>
