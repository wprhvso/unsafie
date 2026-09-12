<script>
  import { onMount } from 'svelte';

  import 'github-markdown-css/github-markdown.css';
  import 'katex/dist/katex.min.css';
  import '$lib/highlight.css';

  import Entry from '$lib/components/live/Entry.svelte';
  import Icon from '$lib/components/live/Icon.svelte';
  import ContextBar from '$lib/components/live/ContextBar.svelte';
  import Waterfall from '$lib/components/Waterfall.svelte';
  import Json from '$lib/components/Json.svelte';
  import Badge from '$lib/components/Badge.svelte';
  import { watch } from '$lib/live/stream.js';
  import { timeline } from '$lib/live/timeline.svelte.js';
  import { zoomer } from '$lib/zoom.js';

  let { token } = $props();

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
  let traceData = $state(null);
  let showTrace = $state(false);
  let showLogs = $state(false);

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
    fetch(`/api/pages/${token}/trace`)
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => {
        if (d && (d.spans?.length || d.logs?.length)) {
          traceData = d;
        }
      })
      .catch(() => {});

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
    {#if feed.model}<span class="mono model" title="model">{feed.model}</span>{/if}
    {#if feed.effort}<span class="chip" title="effort">effort {feed.effort}</span>{/if}
  </div>

  <div class="side end">
    {#if traceData?.spans?.length || traceData?.logs?.length}
      <button
        class="action-btn"
        class:active={showTrace}
        onclick={() => (showTrace = !showTrace)}
        title="Toggle Waterfall Trace"
      >
        <span class="mono">⚡ Trace</span>
      </button>
      <button
        class="action-btn"
        class:active={showLogs}
        onclick={() => (showLogs = !showLogs)}
        title="Toggle Integrated System Logs"
      >
        <span class="mono">📋 Logs ({traceData?.logs?.length || 0})</span>
      </button>
      <span class="sep"></span>
    {/if}
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

<ContextBar context={feed.context} limit={feed.contextLimit} />
{#if showTrace && traceData}
  <div class="trace-box">
    <Waterfall data={traceData} />
  </div>
{/if}
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

      {#if showLogs && traceData?.logs?.length}
        <div class="sys-logs-box">
          <div class="sys-logs-title mono bold small">System & Runtime Logs ({traceData.logs.length})</div>
          <ul class="sys-logs-list">
            {#each traceData.logs as l, idx (idx)}
              {@const lvl = (l.level || 'info').toLowerCase()}
              {@const tone = lvl === 'error' ? 'bad' : lvl === 'warn' || lvl === 'warning' ? 'warn' : 'ok'}
              <li class="sys-log-line">
                <div class="row spread">
                  <div class="row gap">
                    <Badge {tone}>{lvl}</Badge>
                    <span class="mono event-txt">{l.event || l.message || '—'}</span>
                    {#if l.logger}<span class="mono muted small">{l.logger}</span>{/if}
                  </div>
                  <span class="mono muted small">{l.timestamp || l._time || ''}</span>
                </div>
                <div class="sys-log-json">
                  <Json value={l} />
                </div>
              </li>
            {/each}
          </ul>
        </div>
      {/if}
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
    gap: 0.6rem;
    padding: 0.45rem 0.7rem;
    background: var(--live-bar);
    backdrop-filter: saturate(140%) blur(10px);
    border-bottom: 1px solid var(--border);
    font-size: 0.82rem;
    overflow-x: auto;
    -webkit-overflow-scrolling: touch;
    scrollbar-width: none;
  }
  .bar::-webkit-scrollbar {
    display: none;
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
    flex: 1 1 auto;
    min-width: 0;
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

  .chip {
    padding: 0.05rem 0.4rem;
    border: 1px solid var(--border);
    border-radius: 999px;
    font-size: 0.72rem;
    background: var(--panel);
    color: var(--muted);
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
    .chip,
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

  .action-btn {
    display: inline-flex;
    align-items: center;
    padding: 0.2rem 0.5rem;
    font-size: 0.78rem;
    border-radius: 5px;
    border: 1px solid var(--border);
    background: var(--panel);
    color: var(--text);
    cursor: pointer;
    transition: all 0.15s ease;
  }
  .action-btn.active {
    background: color-mix(in srgb, var(--accent) 15%, transparent);
    color: var(--accent);
    border-color: var(--accent);
  }
  .trace-box {
    border-bottom: 2px solid var(--border);
    background: var(--panel);
    max-height: 52vh;
    overflow-y: auto;
    overflow-x: auto;
    -webkit-overflow-scrolling: touch;
  }
  .sys-logs-box {
    margin-top: 2rem;
    border: 1px solid var(--border);
    border-radius: var(--radius);
    background: var(--panel);
    overflow: hidden;
  }
  .sys-logs-title {
    padding: 0.6rem 1rem;
    background: var(--bg);
    border-bottom: 1px solid var(--border);
  }
  .sys-logs-list {
    list-style: none;
    margin: 0;
    padding: 0;
  }
  .sys-log-line {
    padding: 0.5rem 1rem;
    border-bottom: 1px solid var(--border);
  }
  .sys-log-line:last-child {
    border-bottom: 0;
  }
  .gap {
    gap: 0.5rem;
  }
  .event-txt {
    font-size: 0.85rem;
  }
  .sys-log-json {
    margin-top: 0.2rem;
  }
</style>
