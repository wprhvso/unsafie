<script>
  let { data } = $props();

  let expanded = $state({});
  let search = $state('');
  let hideShort = $state(false);

  function toggle(id) {
    expanded[id] = !expanded[id];
  }

  function formatMs(ms) {
    if (ms === undefined || ms === null || Number.isNaN(ms)) return '0ms';
    if (ms < 1000) return `${ms.toFixed(ms < 10 ? 1 : 0)}ms`;
    return `${(ms / 1000).toFixed(1)}s`;
  }

  function shortTrace(tid) {
    if (!tid || tid.length <= 16) return tid || '';
    return `${tid.slice(0, 8)}…${tid.slice(-6)}`;
  }

  let totalMs = $derived(Math.max(1, data?.total_duration_ms || 1));
  let spans = $derived(data?.spans || []);

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
      if (d > 8) break;
    }
    return d;
  }

  let spanMap = $derived(Object.fromEntries(spans.map((s) => [s.id, s])));
</script>

<div class="waterfall-container">
  <div class="toolbar spread">
    <div class="row wrap-gap">
      {#if data?.trace_id}
        <span class="mono muted small trace-text" title={data.trace_id}>
          trace: {shortTrace(data.trace_id)}
        </span>
      {/if}
    </div>
    <div class="row wrap-gap end-controls">
      <span class="badge ok">{formatMs(totalMs)}</span>
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
    </div>
  </div>

  {#if filteredSpans.length === 0}
    <p class="pad muted">No spans match the criteria.</p>
  {:else}
    <div class="waterfall-scroll">
      <div class="waterfall-table">
        <div class="ruler-row">
          <div class="span-label-col muted small">Span / Operation</div>
          <div class="timeline-col ruler">
            <div class="ruler-grid-line" style="left: 0%"></div>
            <div class="ruler-grid-line" style="left: 25%"></div>
            <div class="ruler-grid-line" style="left: 50%"></div>
            <div class="ruler-grid-line" style="left: 75%"></div>
            <div class="ruler-grid-line" style="left: 100%"></div>
            <span class="ruler-label">0</span>
            <span class="ruler-label hide-mobile">{formatMs(totalMs * 0.25)}</span>
            <span class="ruler-label">{formatMs(totalMs * 0.5)}</span>
            <span class="ruler-label hide-mobile">{formatMs(totalMs * 0.75)}</span>
            <span class="ruler-label">{formatMs(totalMs)}</span>
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
                <div class="span-label-col" style="padding-left: {depth * 10 + 6}px">
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
                    title="{span.name}: {formatMs(span.duration_ms)}"
                  ></div>
                  <span class="bar-label mono" style="left: {Math.min(84, left + width + 0.8)}%">
                    {formatMs(span.duration_ms)}
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
                    <span>Start: +{formatMs(span.start_ms)}</span>
                    <span>Duration: {formatMs(span.duration_ms)}</span>
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
      </div>
    </div>
  {/if}
</div>

<style>
  .waterfall-container {
    display: flex;
    flex-direction: column;
    width: 100%;
  }
  .toolbar {
    padding: 0.5rem 0.8rem;
    border-bottom: 1px solid var(--border);
    background: var(--bg);
    gap: 0.6rem;
    flex-wrap: wrap;
  }
  .wrap-gap {
    gap: 0.6rem;
    align-items: center;
    flex-wrap: wrap;
  }
  .end-controls {
    flex-wrap: wrap;
  }
  .trace-text {
    font-size: 0.75rem;
    max-width: 220px;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .toggle-btn {
    border: 1px solid var(--border);
    border-radius: 5px;
    background: var(--panel);
    padding: 0.2rem 0.45rem;
    font-size: 0.76rem;
    color: var(--muted);
    cursor: pointer;
    white-space: nowrap;
  }
  .toggle-btn.active {
    background: color-mix(in srgb, var(--accent) 15%, transparent);
    color: var(--accent);
    border-color: var(--accent);
  }
  .filter-input {
    font: inherit;
    font-size: 0.78rem;
    padding: 0.18rem 0.45rem;
    border: 1px solid var(--border);
    border-radius: 5px;
    background: var(--panel);
    color: var(--text);
    width: 110px;
  }
  .waterfall-scroll {
    width: 100%;
    overflow-x: auto;
    -webkit-overflow-scrolling: touch;
  }
  .waterfall-table {
    min-width: 480px;
    width: 100%;
  }
  .ruler-row {
    display: flex;
    padding: 0.35rem 0.6rem;
    border-bottom: 1px solid var(--border);
    background: var(--panel);
  }
  .ruler {
    display: flex;
    justify-content: space-between;
    font-size: 0.7rem;
    color: var(--muted);
    font-family: var(--mono);
    position: relative;
  }
  .ruler-label {
    z-index: 1;
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
    opacity: 0.25;
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
    min-height: 2rem;
    cursor: pointer;
    user-select: none;
    transition: background 0.1s ease;
  }
  .span-row:hover {
    background: color-mix(in srgb, var(--accent) 6%, transparent);
  }
  .span-label-col {
    width: 38%;
    min-width: 150px;
    display: flex;
    align-items: center;
    gap: 0.35rem;
    padding: 0.25rem 0.5rem;
    overflow: hidden;
    white-space: nowrap;
    flex-shrink: 0;
  }
  .type-tag {
    font-size: 0.64rem;
    padding: 0 0.25rem;
    border-radius: 3px;
    border: 1px solid;
    font-weight: 600;
    flex-shrink: 0;
  }
  .toggle-icon {
    font-size: 0.72rem;
    color: var(--muted);
    width: 0.7rem;
    flex-shrink: 0;
  }
  .span-name {
    font-size: 0.78rem;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .timeline-col {
    width: 62%;
    position: relative;
    height: 1.5rem;
    display: flex;
    align-items: center;
    padding-right: 3.2rem;
  }
  .bar-fill {
    position: absolute;
    height: 0.75rem;
    border-radius: 3px;
    min-width: 3px;
    opacity: 0.85;
  }
  .bar-label {
    position: absolute;
    font-size: 0.68rem;
    color: var(--muted);
    white-space: nowrap;
  }
  .span-details {
    padding: 0.5rem 0.8rem 0.7rem 1.8rem;
    background: color-mix(in srgb, var(--panel) 90%, var(--bg));
    border-top: 1px dashed var(--border);
  }
  .details-meta {
    margin-bottom: 0.4rem;
    gap: 1rem;
    flex-wrap: wrap;
  }
  .tags-table-wrap {
    overflow-x: auto;
  }
  .tags-table {
    width: 100%;
    border-collapse: collapse;
    font-size: 0.78rem;
  }
  .tags-table td {
    padding: 0.2rem 0.35rem;
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
  .pad {
    padding: 0.8rem;
  }

  @media (max-width: 640px) {
    .hide-mobile {
      display: none;
    }
    .filter-input {
      width: 85px;
    }
    .span-label-col {
      width: 42%;
      min-width: 140px;
    }
    .timeline-col {
      width: 58%;
      padding-right: 2.5rem;
    }
  }
</style>
