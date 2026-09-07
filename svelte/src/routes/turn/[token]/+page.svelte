<script>
  import { onMount } from 'svelte';
  import { page } from '$app/state';

  import 'github-markdown-css/github-markdown.css';
  import 'katex/dist/katex.min.css';
  import '$lib/highlight.css';

  import Entry from '$lib/components/live/Entry.svelte';
  import Icon from '$lib/components/live/Icon.svelte';
  import Meters from '$lib/components/live/Meters.svelte';
  import { watch } from '$lib/live/stream.js';
  import { timeline } from '$lib/live/timeline.svelte.js';
  import { zoomer } from '$lib/zoom.js';

  const token = page.params.token;
  const log = timeline();
  const feed = log.state;

  const STICK = 140;
  const TICK = 250;

  let status = $state('loading');
  let meta = $state(null);
  let follow = $state(true);
  let zoom = $state(1);
  let now = $state(Date.now());
  let overrides = $state({});
  let openByDefault = $state(false);
  let control = $state.raw(null);

  const isOpen = (id) => overrides[id] ?? openByDefault;

  function toggle(id) {
    overrides = { ...overrides, [id]: !isOpen(id) };
  }

  function expandAll() {
    overrides = {};
    openByDefault = true;
  }

  function collapseAll() {
    overrides = {};
    openByDefault = false;
  }

  const running = $derived(status === 'live' || status === 'reconnecting');
  const outcome = $derived(feed.outcome ?? meta?.status ?? null);

  const elapsed = $derived.by(() => {
    const from = feed.startedAt ?? meta?.created_at;
    if (!from) return null;
    const till = feed.endedAt ?? meta?.finished_at;
    const ms = (till ? new Date(till).getTime() : now) - new Date(from).getTime();
    return ms >= 0 ? ms : null;
  });

  function clock(ms) {
    if (ms === null) return '—';
    const seconds = Math.floor(ms / 1000);
    const s = String(seconds % 60).padStart(2, '0');
    const m = Math.floor(seconds / 60) % 60;
    const h = Math.floor(seconds / 3600);
    return h ? `${h}:${String(m).padStart(2, '0')}:${s}` : `${m}:${s}`;
  }

  const tokens = $derived(
    (feed.usage.input_tokens ?? 0) +
      (feed.usage.cache_read_input_tokens ?? 0) +
      (feed.usage.cache_creation_input_tokens ?? 0) +
      (feed.usage.output_tokens ?? 0)
  );

  const cost = $derived(feed.cost || meta?.cost_usd || 0);

  const LABEL = {
    loading: 'connecting',
    live: 'live',
    reconnecting: 'reconnecting',
    done: 'finished',
    gone: 'link expired',
    error: 'unavailable'
  };

  function bottom() {
    return document.documentElement.scrollHeight - window.innerHeight - window.scrollY;
  }

  function toLatest() {
    follow = true;
    window.scrollTo({ top: document.documentElement.scrollHeight });
  }

  onMount(() => {
    control = zoomer({
      key: 'live-zoom',
      variable: '--live-zoom',
      onchange: (value) => (zoom = value)
    });

    const stop = watch(token, {
      onSnapshot: (data) => (meta = data.turn ?? null),
      onFrame: (frame) => log.apply(frame),
      onGap: () => log.reset(),
      onStatus: (value) => (status = value)
    });

    const onScroll = () => {
      follow = bottom() < STICK;
    };
    window.addEventListener('scroll', onScroll, { passive: true });

    const timer = setInterval(() => {
      now = Date.now();
      if (follow && bottom() > 2) window.scrollTo({ top: document.documentElement.scrollHeight });
    }, TICK);

    return () => {
      clearInterval(timer);
      window.removeEventListener('scroll', onScroll);
      stop();
      control?.stop();
      control = null;
    };
  });
</script>

<svelte:head>
  <title>unsafie — turn</title>
  <meta name="color-scheme" content="light dark" />
  <meta name="robots" content="noindex" />
  <link rel="icon" href="data:," />
</svelte:head>

<div class="top">
<header class="bar">
  <div class="side">
    <span class="dot {status}" aria-hidden="true"></span>
    <span class="what">{LABEL[status] ?? status}</span>
    {#if outcome && !running}
      <span class="badge {outcome === 'failed' ? 'bad' : 'ok'}">{outcome}</span>
    {/if}
  </div>

  <div class="stats">
    <span title="elapsed"><b>{clock(elapsed)}</b></span>
    <span title="model requests">{feed.steps} steps</span>
    <span title="tool calls">{feed.calls} calls</span>
    {#if feed.model}<span class="mono model" title="model">{feed.model}</span>{/if}
  </div>

  <div class="side end">
    <button onclick={collapseAll} title="Collapse everything" aria-label="Collapse everything">
      <Icon name="collapse" size={14} />
    </button>
    <button onclick={expandAll} title="Expand everything" aria-label="Expand everything">
      <Icon name="expand" size={14} />
    </button>
    <span class="sep"></span>
    <button onclick={() => control?.out()} title="Zoom out" aria-label="Zoom out">
      <Icon name="zoomOut" size={14} />
    </button>
    <button class="level mono" onclick={() => control?.reset()} title="Reset the zoom">
      {Math.round(zoom * 100)}%
    </button>
    <button onclick={() => control?.in()} title="Zoom in" aria-label="Zoom in">
      <Icon name="zoomIn" size={14} />
    </button>
  </div>
</header>

<Meters
  {cost}
  budget={feed.budget}
  context={feed.context}
  limit={feed.contextLimit}
  {tokens}
  live={running}
/>
</div>

<main>
  {#if status === 'gone'}
    <div class="empty">
      <h1>This link has expired</h1>
      <p class="muted">A turn is watchable while it runs and for a while after. This one is past that.</p>
    </div>
  {:else if status === 'error'}
    <div class="empty">
      <h1>Nothing to show</h1>
      <p class="muted">The event store did not answer. Reload in a moment.</p>
    </div>
  {:else if !feed.items.length}
    <div class="empty">
      <h1>Waiting for the first frame…</h1>
      <p class="muted">Everything the model does lands here as it happens.</p>
    </div>
  {:else}
    <div class="log">
      {#each feed.items as item (item.id)}
        <Entry {item} open={isOpen(item.id)} ontoggle={toggle} />
      {/each}
    </div>
    {#if running}
      <p class="tail muted small">
        <span class="blip"></span> waiting for the model…
      </p>
    {/if}
  {/if}
</main>

{#if !follow && feed.items.length}
  <button class="jump" onclick={toLatest} title="Jump to the latest">
    <Icon name="down" size={15} /> latest
  </button>
{/if}

<style>
  :global(:root) {
    color-scheme: light dark;
    --live-zoom: 1;
    --live-sunken: #f6f7f9;
    --live-think: #8250df;
    --live-key: #6639ba;
    --live-string: #0a6640;
    --live-number: #0550ae;
    --live-atom: #a4413a;
    --live-bar: rgba(251, 251, 250, 0.82);
  }

  @media (prefers-color-scheme: dark) {
    :global(:root) {
      --live-sunken: #101014;
      --live-think: #b389f5;
      --live-key: #c39bff;
      --live-string: #7ee2b8;
      --live-number: #79b8ff;
      --live-atom: #ff9492;
      --live-bar: rgba(19, 19, 22, 0.82);
    }
  }

  .top {
    position: sticky;
    top: 0;
    z-index: 20;
  }

  .bar {
    display: flex;
    align-items: center;
    gap: 0.8rem;
    padding: 0.45rem 0.9rem;
    background: var(--live-bar);
    backdrop-filter: saturate(140%) blur(10px);
    border-bottom: 1px solid var(--border);
    font-size: 0.82rem;
  }

  .side {
    display: flex;
    align-items: center;
    gap: 0.35rem;
    flex: 0 0 auto;
  }

  .side.end {
    margin-left: auto;
  }

  .stats {
    display: flex;
    align-items: center;
    gap: 0.75rem;
    color: var(--muted);
    overflow: hidden;
    white-space: nowrap;
  }

  .stats b {
    color: var(--text);
    font-variant-numeric: tabular-nums;
  }

  .model {
    overflow: hidden;
    text-overflow: ellipsis;
    max-width: 12rem;
  }

  .what {
    font-weight: 600;
  }

  .dot {
    width: 0.5rem;
    height: 0.5rem;
    border-radius: 50%;
    background: var(--muted);
  }

  .dot.live {
    background: var(--accent);
    animation: beat 1.6s ease-in-out infinite;
  }

  .dot.loading,
  .dot.reconnecting {
    background: var(--warn);
    animation: beat 1s ease-in-out infinite;
  }

  .dot.done {
    background: var(--ok);
  }

  .dot.gone,
  .dot.error {
    background: var(--bad);
  }

  @keyframes beat {
    50% {
      opacity: 0.25;
    }
  }

  .badge {
    padding: 0.05rem 0.4rem;
    border-radius: 999px;
    font-size: 0.72rem;
    border: 1px solid var(--border);
  }

  .badge.ok {
    color: var(--ok);
  }

  .badge.bad {
    color: var(--bad);
  }

  .bar button {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    padding: 0.25rem 0.35rem;
    border-color: transparent;
    background: none;
    color: var(--muted);
  }

  .bar button:hover {
    color: var(--accent);
    border-color: var(--border);
  }

  .bar .level {
    font-size: 0.74rem;
    min-width: 3rem;
  }

  .sep {
    width: 1px;
    height: 1rem;
    background: var(--border);
    margin: 0 0.15rem;
  }

  main {
    box-sizing: border-box;
    width: 100%;
    max-width: calc(58rem / var(--live-zoom));
    margin: 0 auto;
    padding: calc(0.8rem / var(--live-zoom)) calc(0.9rem / var(--live-zoom))
      calc(6rem / var(--live-zoom));
    zoom: var(--live-zoom);
  }

  .log {
    display: flex;
    flex-direction: column;
  }

  .empty {
    text-align: center;
    margin: 22vh auto 0;
    max-width: 32rem;
  }

  .empty h1 {
    font-size: 1.15rem;
    font-weight: 600;
  }

  .tail {
    display: flex;
    align-items: center;
    gap: 0.45rem;
    margin: 0.8rem 0 0 2.1rem;
  }

  .blip {
    width: 0.45rem;
    height: 0.45rem;
    border-radius: 50%;
    background: var(--accent);
    animation: beat 1.2s ease-in-out infinite;
  }

  .jump {
    position: fixed;
    right: 1rem;
    bottom: 1rem;
    z-index: 30;
    display: inline-flex;
    align-items: center;
    gap: 0.3rem;
    padding: 0.4rem 0.7rem;
    border-radius: 999px;
    box-shadow: 0 6px 20px rgb(0 0 0 / 18%);
    font-size: 0.8rem;
  }

  @media (max-width: 720px) {
    .stats {
      gap: 0.5rem;
      font-size: 0.76rem;
    }

    .model,
    .what {
      display: none;
    }
  }

  @media (prefers-reduced-motion: reduce) {
    .dot,
    .blip {
      animation: none;
    }
  }
</style>
