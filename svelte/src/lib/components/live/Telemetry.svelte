<script>
  import { onMount } from 'svelte';
  import { when } from '$lib/format.js';
  import Waterfall from '$lib/components/Waterfall.svelte';
  import Json from '$lib/components/Json.svelte';
  import Badge from '$lib/components/Badge.svelte';
  import { zoomer } from '$lib/zoom.js';

  let { token } = $props();

  let data = $state(null);
  let loading = $state(true);
  let error = $state(null);
  let activeTab = $state('waterfall');
  let logFilter = $state('ALL');
  let searchLog = $state('');

  function took(ms) {
    if (ms === undefined || ms === null) return '0ms';
    if (ms < 1000) return `${ms.toFixed(0)}ms`;
    return `${(ms / 1000).toFixed(2)}s`;
  }

  onMount(() => {
    const control = zoomer({
      key: 'telemetry-zoom',
      variable: '--telem-zoom'
    });

    fetch(`/api/pages/${token}/trace`)
      .then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.json();
      })
      .then((d) => {
        data = d;
        loading = false;
      })
      .catch((e) => {
        error = e.message || 'Failed to load telemetry';
        loading = false;
      });

    return () => {
      control?.stop();
    };
  });

  let totalMs = $derived(Math.max(1, data?.total_duration_ms || 1));
  let spans = $derived(data?.spans || []);
  let logs = $derived(data?.logs || []);

  let filteredLogs = $derived(
    logs.filter((l) => {
      const lvl = (l.level || 'info').toUpperCase();
      if (logFilter === 'ERROR' && lvl !== 'ERROR') return false;
      if (logFilter === 'WARN' && lvl !== 'WARN' && lvl !== 'WARNING') return false;
      if (logFilter === 'INFO' && lvl !== 'INFO') return false;
      if (searchLog) {
        const q = searchLog.toLowerCase();
        return (
          (l.event || '').toLowerCase().includes(q) ||
          (l.message || '').toLowerCase().includes(q) ||
          (l.logger || '').toLowerCase().includes(q) ||
          JSON.stringify(l).toLowerCase().includes(q)
        );
      }
      return true;
    })
  );

  let failedSpans = $derived(spans.filter((s) => s.status === 'error'));
</script>

<svelte:head>
  <title>unsafie — telemetry</title>
  <meta name="color-scheme" content="light dark" />
  <meta name="robots" content="noindex" />
</svelte:head>

<div class="telem-page">
  <header class="telem-header spread">
    <div class="row header-left">
      <span class="icon-bolt">⚡</span>
      <h1 class="telem-title">Diagnostics & Telemetry</h1>
      <span class="mono muted small">/{token}</span>
    </div>


  </header>

  <main class="telem-main">
    {#if loading}
      <div class="center-box muted">
        <p>Loading execution telemetry…</p>
      </div>
    {:else if error}
      <div class="center-box bad">
        <p>{error}</p>
      </div>
    {:else}
      <section class="summary-grid">
        <div class="stat-card">
          <span class="stat-label muted">Duration</span>
          <span class="stat-value mono bold">{took(totalMs)}</span>
        </div>
        <div class="stat-card">
          <span class="stat-label muted">Spans</span>
          <span class="stat-value mono bold">{spans.length}</span>
        </div>
        <div class="stat-card">
          <span class="stat-label muted">Logs</span>
          <span class="stat-value mono bold">{logs.length}</span>
        </div>
        <div class="stat-card">
          <span class="stat-label muted">Status</span>
          <span class="stat-value mono bold">
            {#if failedSpans.length > 0}
              <span class="badge bad">Errors ({failedSpans.length})</span>
            {:else}
              <span class="badge ok">Clean</span>
            {/if}
          </span>
        </div>
      </section>

      {#if failedSpans.length > 0}
        <section class="error-banner">
          <div class="error-header bold">Failure Diagnosis</div>
          {#each failedSpans as errSpan}
            <div class="error-row row spread">
              <span class="mono bold">{errSpan.name}</span>
              <span class="mono muted small">+{errSpan.start_ms}ms ({took(errSpan.duration_ms)})</span>
            </div>
            {#if errSpan.tags?.error}
              <pre class="error-pre">{errSpan.tags.error}</pre>
            {/if}
          {/each}
        </section>
      {/if}

      <div class="tabs-nav row">
        <button
          class="tab-nav-btn"
          class:active={activeTab === 'waterfall'}
          onclick={() => (activeTab = 'waterfall')}
        >
          ⚡ Execution Waterfall ({spans.length})
        </button>
        <button
          class="tab-nav-btn"
          class:active={activeTab === 'logs'}
          onclick={() => (activeTab = 'logs')}
        >
          📋 System & Runtime Logs ({logs.length})
        </button>
      </div>

      {#if activeTab === 'waterfall'}
        <section class="section-card">
          <div class="waterfall-embed">
            <Waterfall {data} />
          </div>
        </section>
      {:else if activeTab === 'logs'}
        <section class="section-card">
          <div class="section-head spread">
            <h2 class="section-title">System & Runtime Logs</h2>
            <div class="row filter-controls">
              <div class="filter-pills">
                <button class:active={logFilter === 'ALL'} onclick={() => (logFilter = 'ALL')}>All</button>
                <button class:active={logFilter === 'ERROR'} onclick={() => (logFilter = 'ERROR')}>Errors</button>
                <button class:active={logFilter === 'WARN'} onclick={() => (logFilter = 'WARN')}>Warnings</button>
                <button class:active={logFilter === 'INFO'} onclick={() => (logFilter = 'INFO')}>Info</button>
              </div>
              <input
                type="text"
                placeholder="Search logs..."
                class="search-input"
                bind:value={searchLog}
              />
            </div>
          </div>

          {#if filteredLogs.length === 0}
            <p class="pad muted">No logs matching filter.</p>
          {:else}
            <ul class="logs-stream">
              {#each filteredLogs as l, idx (idx)}
                {@const lvl = (l.level || 'info').toLowerCase()}
                {@const tone = lvl === 'error' ? 'bad' : lvl === 'warn' || lvl === 'warning' ? 'warn' : 'ok'}
                <li class="log-row">
                  <div class="row spread log-line-head">
                    <div class="row gap">
                      <Badge {tone}>{lvl}</Badge>
                      <span class="mono bold event-txt">{l.event || l.message || '—'}</span>
                      {#if l.logger}<span class="mono muted small">{l.logger}</span>{/if}
                    </div>
                    <time class="mono muted tiny">{when(l.timestamp || l._time)}</time>
                  </div>
                  <div class="log-details">
                    <Json value={l} />
                  </div>
                </li>
              {/each}
            </ul>
          {/if}
        </section>
      {/if}
    {/if}
  </main>
</div>

<style>
  .telem-page {
    min-height: 100vh;
    background: var(--bg);
    color: var(--text);
    width: 100%;
    zoom: var(--telem-zoom, 1);
  }
  .telem-header {
    position: static;
    padding: 0.75rem 1.2rem;
    background: var(--panel);
    border-bottom: 1px solid var(--border);
    align-items: center;
  }
  .icon-bolt {
    color: var(--accent);
    font-size: 1.1rem;
  }
  .telem-title {
    font-size: 1.05rem;
    font-weight: 600;
    margin: 0;
  }
  .header-left {
    gap: 0.6rem;
    align-items: center;
  }
  .header-right {
    gap: 0.8rem;
    align-items: center;
  }
  .tabs-nav {
    border-bottom: 1px solid var(--border);
    gap: 0.4rem;
    margin-top: 0.4rem;
  }
  .tab-nav-btn {
    border: 0;
    border-bottom: 2px solid transparent;
    border-radius: 0;
    background: none;
    padding: 0.5rem 0.9rem;
    font-size: 0.86rem;
    font-weight: 500;
    color: var(--muted);
    cursor: pointer;
    transition: all 0.12s ease;
  }
  .tab-nav-btn:hover {
    color: var(--text);
  }
  .tab-nav-btn.active {
    color: var(--accent);
    border-bottom-color: var(--accent);
  }
  .telem-main {
    max-width: 68rem;
    margin: 0 auto;
    padding: 1.2rem 1rem 4rem;
    display: flex;
    flex-direction: column;
    gap: 1.2rem;
  }
  .summary-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
    gap: 0.8rem;
  }
  .stat-card {
    background: var(--panel);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    padding: 0.7rem 1rem;
    display: flex;
    flex-direction: column;
    gap: 0.2rem;
  }
  .stat-label {
    font-size: 0.76rem;
    text-transform: uppercase;
    letter-spacing: 0.04em;
  }
  .stat-value {
    font-size: 1.15rem;
  }
  .error-banner {
    background: color-mix(in srgb, var(--bad) 8%, var(--panel));
    border: 1.5px solid var(--bad);
    border-radius: var(--radius);
    padding: 0.8rem 1.1rem;
    display: flex;
    flex-direction: column;
    gap: 0.4rem;
  }
  .error-header {
    color: var(--bad);
    font-size: 0.95rem;
  }
  .error-pre {
    margin: 0.3rem 0 0;
    padding: 0.5rem 0.7rem;
    background: var(--panel);
    border: 1px solid var(--border);
    border-radius: 4px;
    font-family: var(--mono);
    font-size: 0.8rem;
    white-space: pre-wrap;
    max-height: 14rem;
    overflow-y: auto;
  }
  .section-card {
    background: var(--panel);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    overflow: hidden;
  }
  .section-head {
    padding: 0.65rem 1rem;
    background: var(--bg);
    border-bottom: 1px solid var(--border);
    align-items: center;
    flex-wrap: wrap;
    gap: 0.6rem;
  }
  .section-title {
    font-size: 0.92rem;
    font-weight: 600;
    margin: 0;
  }
  .filter-controls {
    gap: 0.6rem;
    align-items: center;
    flex-wrap: wrap;
  }
  .filter-pills {
    display: flex;
    border: 1px solid var(--border);
    border-radius: 5px;
    overflow: hidden;
  }
  .filter-pills button {
    border: 0;
    background: var(--panel);
    padding: 0.18rem 0.5rem;
    font-size: 0.75rem;
    cursor: pointer;
  }
  .filter-pills button.active {
    background: var(--accent);
    color: #fff;
  }
  .search-input {
    font: inherit;
    font-size: 0.78rem;
    padding: 0.18rem 0.45rem;
    border: 1px solid var(--border);
    border-radius: 5px;
    background: var(--panel);
    color: var(--text);
    width: 120px;
  }
  .logs-stream {
    list-style: none;
    margin: 0;
    padding: 0;
  }
  .log-row {
    padding: 0.55rem 1rem;
    border-bottom: 1px solid var(--border);
  }
  .log-row:last-child {
    border-bottom: 0;
  }
  .log-line-head {
    gap: 0.6rem;
    align-items: center;
  }
  .gap {
    gap: 0.5rem;
    align-items: center;
  }
  .event-txt {
    font-size: 0.82rem;
  }
  .log-details {
    margin-top: 0.25rem;
  }
  .center-box {
    padding: 3rem 1rem;
    text-align: center;
    font-size: 1rem;
  }
  .pad {
    padding: 1rem;
  }
  .tiny { font-size: 0.73rem; }
  .small { font-size: 0.82rem; }
  .mono { font-family: var(--mono); }
  .bold { font-weight: 600; }
</style>
