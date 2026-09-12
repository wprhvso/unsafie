<script>
  import Badge from '$lib/components/Badge.svelte';
  import Json from '$lib/components/Json.svelte';

  let { data } = $props();

  let view = $state('waterfall');
  let expanded = $state({});
  let search = $state('');
  let hideShort = $state(false);

  function toggle(id) {
    expanded[id] = !expanded[id];
  }

  let totalMs = $derived(Math.max(1, data?.total_duration_ms || 1));
  let spans = $derived(data?.spans || []);
  let logs = $derived(data?.logs || []);

  function getSpanCategory(name, status) {
    if (status === 'error') return { cat: 'ERR', tone: 'bad', color: 'var(--bad)' };
    if (name.includes('gemini') || name.includes('gen_ai')) return { cat: 'LLM', tone: 'accent', color: '#8b5cf6' };
    if (name.includes('bwrap') || name.includes('runner')) return { cat: 'RUNNER', tone: 'warn', color: '#f59e0b' };
    if (name.startsWith('tg.') || name.includes('telegram')) return { cat: 'TG', tone: 'ok', color: '#0ea5e9' };
    if (name.includes('SELECT') || name.includes('INSERT') || name.includes('UPDATE') || name === 'connect') {
      return { cat: 'DB', tone: 'ok', color: '#38bdf8' };
    }
    if (name.startsWith('POST') || name.startsWith('GET') || name.startsWith('DELETE') || name.startsWith('PUT')) {
      return { cat: 'HTTP', tone: 'warn', color: '#ec4899' };
    }
    if (name.startsWith('agent.') || name.startsWith('turn.')) {
      return { cat: 'AGENT', tone: 'ok', color: '#10b981' };
    }
    return { cat: 'SYS', tone: 'muted', color: 'var(--muted)' };
  }

  let filteredSpans = $derived(
    spans.filter((s) => {
      if (hideShort && s.duration_ms < 1.0) return false;
      if (search) {
        const q = search.toLowerCase();
        return s.name.toLowerCase().includes(q) || JSON.stringify(s.tags || {}).toLowerCase().includes(q);
      }
      return true;
    })
  );

  function getDepth(span, spanMap) {
    let d = 0;
    let curr = span.parent_id;
    while (curr && spanMap[curr]) {
      d += 1;
      curr = spanMap[curr].parent_id;
      if (d > 10) break;
    }
    return d;
  }

  let spanMap = $derived(Object.fromEntries(spans.map((s) => [s.id, s])));
</script>

<div class="waterfall-container">
  <div class="toolbar spread">
    <div class="row wrap-gap">
      <div class="tab-group">
        <button class:active={view === 'waterfall'} onclick={() => (view = 'waterfall')}>
          Waterfall ({spans.length})
        </button>
        <button class:active={view === 'logs'} onclick={() => (view = 'logs')}>
          Logs ({logs.length})
        </button>
      </div>
      {#if data?.trace_id}
        <span class="mono muted small">trace: {data.trace_id}</span>
      {/if}
    </div>
    <div class="row wrap-gap">
      <span class="badge ok">{totalMs.toFixed(1)} ms</span>
      {#if view === 'waterfall'}
        <button
          class="toggle-btn"
          class:active={hideShort}
          onclick={() => (hideShort = !hideShort)}
          title="Toggle micro-spans under 1ms"
        >
          {hideShort ? 'Show all' : 'Hide < 1ms'}
        </button>
        <input
          type="text"
          placeholder="Filter spans..."
          class="filter-input"
          bind:value={search}
        />
      {/if}
    </div>
  </div>

  {#if view === 'waterfall'}
    {#if filteredSpans.length === 0}
      <p class="pad muted">No spans match the criteria.</p>
    {:else}
      <div class="ruler-row">
        <div class="span-label-col muted small">Span / Operation</div>
        <div class="timeline-col ruler">
          <div class="ruler-grid-line" style="left: 0%"></div>
          <div class="ruler-grid-line" style="left: 25%"></div>
          <div class="ruler-grid-line" style="left: 50%"></div>
          <div class="ruler-grid-line" style="left: 75%"></div>
          <div class="ruler-grid-line" style="left: 100%"></div>
          <span>0ms</span>
          <span>{(totalMs * 0.25).toFixed(0)}ms</span>
          <span>{(totalMs * 0.5).toFixed(0)}ms</span>
          <span>{(totalMs * 0.75).toFixed(0)}ms</span>
          <span>{totalMs.toFixed(0)}ms</span>
        </div>
      </div>

      <div class="spans-list">
        {#each filteredSpans as span (span.id)}
          {@const depth = getDepth(span, spanMap)}
          {@const left = (span.start_ms / totalMs) * 100}
          {@const width = Math.max(0.6, (span.duration_ms / totalMs) * 100)}
          {@const meta = getSpanCategory(span.name, span.status)}

          <div class="span-row-wrap" class:open={expanded[span.id]}>
            <div
              class="span-row"
              role="button"
              tabindex="0"
              onclick={() => toggle(span.id)}
              onkeydown={(e) => e.key === 'Enter' && toggle(span.id)}
            >
              <div class="span-label-col" style="padding-left: {depth * 14 + 8}px">
                <span class="toggle-icon">{expanded[span.id] ? '▾' : '▸'}</span>
                <span class="type-tag mono" style="color: {meta.color}; border-color: {meta.color}">
                  {meta.cat}
                </span>
                <span class="span-name mono" title={span.name}>{span.name}</span>
              </div>

              <div class="timeline-col">
                <div class="grid-line" style="left: 0%"></div>
                <div class="grid-line" style="left: 25%"></div>
                <div class="grid-line" style="left: 50%"></div>
                <div class="grid-line" style="left: 75%"></div>
                <div class="grid-line" style="left: 100%"></div>

                <div
                  class="bar-fill"
                  style="left: {left}%; width: {width}%; background-color: {meta.color};"
                  title="{span.name}: {span.duration_ms}ms"
                ></div>
                <span class="bar-label mono" style="left: {Math.min(91, left + width + 0.6)}%">
                  {span.duration_ms}ms
                </span>
              </div>
            </div>

            {#if expanded[span.id]}
              <div class="span-details">
                <div class="details-meta row small muted">
                  <span>ID: <code class="mono">{span.id}</code></span>
                  {#if span.parent_id}
                    <span>Parent: <code class="mono">{span.parent_id}</code></span>
                  {/if}
                  <span>Start: +{span.start_ms}ms</span>
                  <span>Duration: {span.duration_ms}ms</span>
                </div>
                {#if Object.keys(span.tags || {}).length}
                  <div class="tags-table-wrap">
                    <table class="tags-table">
                      <tbody>
                        {#each Object.entries(span.tags) as [k, v]}
                          <tr>
                            <td class="tag-key mono">{k}</td>
                            <td class="tag-val mono">{typeof v === 'object' ? JSON.stringify(v) : v}</td>
                          </tr>
                        {/each}
                      </tbody>
                    </table>
                  </div>
                {/if}
              </div>
            {/if}
          </div>
        {/each}
      </div>
    {/if}
  {:else if view === 'logs'}
    {#if logs.length === 0}
      <p class="pad muted">No structured logs recorded for this turn.</p>
    {:else}
      <ul class="logs-list">
        {#each logs as log, idx (idx)}
          {@const lvl = (log.level || 'info').toLowerCase()}
          {@const tone = lvl === 'error' ? 'bad' : lvl === 'warning' || lvl === 'warn' ? 'warn' : 'ok'}
          <li class="log-item">
            <div class="log-header row spread">
              <div class="row">
                <Badge {tone}>{lvl}</Badge>
                <span class="log-event mono bold">{log.event || log.message || '—'}</span>
                {#if log.logger}
                  <span class="muted small mono">{log.logger}</span>
                {/if}
              </div>
              <span class="muted small mono">{log.timestamp || log._time || ''}</span>
            </div>
            <div class="log-json">
              <Json value={log} />
            </div>
          </li>
        {/each}
      </ul>
    {/if}
  {/if}
</div>

<style>
  .waterfall-container {
    display: flex;
    flex-direction: column;
  }
  .toolbar {
    padding: 0.6rem 1rem;
    border-bottom: 1px solid var(--border);
    background: var(--bg);
    gap: 0.8rem;
    flex-wrap: wrap;
  }
  .wrap-gap {
    gap: 0.8rem;
    align-items: center;
  }
  .tab-group {
    display: flex;
    border: 1px solid var(--border);
    border-radius: 6px;
    overflow: hidden;
  }
  .tab-group button {
    border: 0;
    border-radius: 0;
    background: var(--panel);
    padding: 0.25rem 0.6rem;
    font-size: 0.82rem;
    cursor: pointer;
  }
  .tab-group button.active {
    background: var(--accent);
    color: #fff;
  }
  .toggle-btn {
    border: 1px solid var(--border);
    border-radius: 5px;
    background: var(--panel);
    padding: 0.2rem 0.5rem;
    font-size: 0.78rem;
    color: var(--muted);
    cursor: pointer;
  }
  .toggle-btn.active {
    background: color-mix(in srgb, var(--accent) 15%, transparent);
    color: var(--accent);
    border-color: var(--accent);
  }
  .filter-input {
    font: inherit;
    font-size: 0.82rem;
    padding: 0.2rem 0.5rem;
    border: 1px solid var(--border);
    border-radius: 5px;
    background: var(--panel);
    color: var(--text);
  }
  .ruler-row {
    display: flex;
    padding: 0.4rem 1rem;
    border-bottom: 1px solid var(--border);
    background: var(--panel);
  }
  .ruler {
    display: flex;
    justify-content: space-between;
    font-size: 0.72rem;
    color: var(--muted);
    font-family: var(--mono);
  }
  .ruler-grid-line {
    position: absolute;
    top: 0;
    bottom: 0;
    width: 1px;
    background: var(--border);
    opacity: 0.5;
  }
  .grid-line {
    position: absolute;
    top: 0;
    bottom: 0;
    width: 1px;
    background: var(--border);
    opacity: 0.3;
    pointer-events: none;
  }
  .spans-list {
    display: flex;
    flex-direction: column;
  }
  .span-row-wrap {
    border-bottom: 1px solid var(--border);
  }
  .span-row-wrap:last-child {
    border-bottom: 0;
  }
  .span-row {
    display: flex;
    align-items: center;
    min-height: 2.1rem;
    cursor: pointer;
    user-select: none;
    transition: background 0.1s ease;
  }
  .span-row:hover {
    background: color-mix(in srgb, var(--accent) 6%, transparent);
  }
  .span-label-col {
    width: 40%;
    min-width: 220px;
    display: flex;
    align-items: center;
    gap: 0.4rem;
    padding: 0.3rem 0.6rem;
    overflow: hidden;
    white-space: nowrap;
  }
  .type-tag {
    font-size: 0.68rem;
    padding: 0.05rem 0.3rem;
    border-radius: 3px;
    border: 1px solid;
    font-weight: 600;
  }
  .toggle-icon {
    font-size: 0.75rem;
    color: var(--muted);
    width: 0.8rem;
  }
  .span-name {
    font-size: 0.82rem;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .timeline-col {
    width: 60%;
    position: relative;
    height: 1.6rem;
    display: flex;
    align-items: center;
    padding-right: 4rem;
  }
  .bar-fill {
    position: absolute;
    height: 0.8rem;
    border-radius: 3px;
    min-width: 3px;
    opacity: 0.85;
  }
  .bar-label {
    position: absolute;
    font-size: 0.72rem;
    color: var(--muted);
    white-space: nowrap;
  }
  .span-details {
    padding: 0.6rem 1rem 0.8rem 2.5rem;
    background: color-mix(in srgb, var(--panel) 90%, var(--bg));
    border-top: 1px dashed var(--border);
  }
  .details-meta {
    margin-bottom: 0.5rem;
    gap: 1.2rem;
    flex-wrap: wrap;
  }
  .tags-table-wrap {
    overflow-x: auto;
  }
  .tags-table {
    width: 100%;
    border-collapse: collapse;
    font-size: 0.8rem;
  }
  .tags-table td {
    padding: 0.2rem 0.4rem;
    border: 1px solid var(--border);
    vertical-align: top;
  }
  .tag-key {
    color: var(--muted);
    width: 25%;
    white-space: nowrap;
  }
  .tag-val {
    word-break: break-all;
  }
  .logs-list {
    list-style: none;
    margin: 0;
    padding: 0;
  }
  .log-item {
    padding: 0.6rem 1rem;
    border-bottom: 1px solid var(--border);
  }
  .log-item:last-child {
    border-bottom: 0;
  }
  .log-header {
    gap: 0.6rem;
    margin-bottom: 0.3rem;
  }
  .log-event {
    font-size: 0.86rem;
  }
  .bold {
    font-weight: 600;
  }
  .pad {
    padding: 1rem;
  }
</style>
