<script>
  import { onMount } from 'svelte';
  import { page } from '$app/state';
  import { api } from '$lib/api.js';
  import { when } from '$lib/format.js';
  import Loader from '$lib/components/Loader.svelte';

  let runId = $derived(page.params.id);
  let run = $state(null);
  let logs = $state('');
  let terminalEl = $state(null);
  let autoscroll = $state(true);
  let search = $state('');
  let busy = $state(false);
  let selectedJob = $state(page.url.searchParams.get('job') || '');

  let cpu = $state(0);
  let peakCpu = $state(0);
  let rss = $state(0);
  let peakRss = $state(0);
  let rx = $state(0);
  let tx = $state(0);

  let evSource = null;

  async function fetchRun() {
    try {
      run = await api.get(`/api/ci/runs/${runId}`);
      if (run?.jobs?.length && !selectedJob) {
        selectedJob = run.jobs[0].name;
      }
    } catch {
    }
  }

  async function rerun() {
    busy = true;
    try {
      const res = await api.post(`/api/ci/runs/${runId}/rerun`);
      if (res?.run_id) {
        window.location.href = `/ci/runs/${res.run_id}`;
      }
    } finally {
      busy = false;
    }
  }

  function setupStream() {
    if (evSource) {
      evSource.close();
      evSource = null;
    }
    logs = '';
    const url = selectedJob
      ? `/api/ci/runs/${runId}/stream?job=${encodeURIComponent(selectedJob)}`
      : `/api/ci/runs/${runId}/stream`;

    evSource = new EventSource(url);

    evSource.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        if (data.type === 'init') {
          logs = data.log || '';
        } else if (data.type === 'log') {
          logs += data.chunk || '';
        } else if (data.type === 'metric') {
          cpu = data.cpu || 0;
          if (cpu > peakCpu) peakCpu = cpu;
          rss = data.rss || 0;
          if (rss > peakRss) peakRss = rss;
          rx = data.rx || 0;
          tx = data.tx || 0;
        } else if (data.type === 'status') {
          if (run) {
            run.status = data.status;
            run.exit_code = data.exit_code;
          }
          fetchRun();
        }
      } catch {
      }

      if (autoscroll && terminalEl) {
        terminalEl.scrollTop = terminalEl.scrollHeight;
      }
    };
  }

  onMount(() => {
    fetchRun().then(setupStream);
    return () => {
      if (evSource) evSource.close();
    };
  });

  const filteredLogs = $derived(
    search
      ? logs.split('\n').filter(l => l.toLowerCase().includes(search.toLowerCase())).join('\n')
      : logs
  );
</script>

<svelte:head><title>{run ? `${run.repo_full_name} #${run.id}` : 'Run'} — unsafie CI</title></svelte:head>

{#if !run}
  <Loader />
{:else}
  <div class="run-header">
    <div class="meta-col">
      <div class="crumbs">
        <a href="/ci">Runs</a> / <span>{run.repo_full_name}</span> / <strong>#{run.id}</strong>
      </div>
      <h1>
        <span class="status-dot {run.status}"></span>
        Commit <code>{run.commit_sha.slice(0, 8)}</code> on <code>{run.branch}</code>
      </h1>
      {#if run.commit_message}
        <p class="commit-desc">{run.commit_message}</p>
      {/if}
      <div class="details-row">
        <span>Trigger: <strong>{run.trigger_event}</strong></span>
        <span>Author: <strong>@{run.sender || 'unknown'}</strong></span>
        <span>Started: <strong>{run.started_at ? when(run.started_at) : 'pending'}</strong></span>
        {#if run.exit_code !== null}
          <span>Exit Code: <strong>{run.exit_code}</strong></span>
        {/if}
      </div>
    </div>

    <div class="actions-col">
      <button class="btn ok" onclick={rerun} disabled={busy}>
        {busy ? 'Triggering…' : '↻ Re-run Workflow'}
      </button>
      <a
        href="/api/ci/runs/{run.id}/logs/raw{selectedJob ? `?job=${encodeURIComponent(selectedJob)}` : ''}"
        download="run-{run.id}{selectedJob ? `-${selectedJob}` : ''}.log"
        class="btn outline"
      >
        ⬇ Download {selectedJob || 'All'} Log
      </a>
    </div>
  </div>

  <div class="telemetry-grid">
    <div class="metric-card">
      <div class="metric-label">CPU Utilization</div>
      <div class="metric-val">{cpu}%</div>
      <div class="metric-sub">Peak: {peakCpu}%</div>
    </div>
    <div class="metric-card">
      <div class="metric-label">Memory (RSS)</div>
      <div class="metric-val">{rss >= 1024 ? `${(rss / 1024).toFixed(2)} GB` : `${rss} MB`}</div>
      <div class="metric-sub">Peak: {peakRss >= 1024 ? `${(peakRss / 1024).toFixed(2)} GB` : `${peakRss} MB`}</div>
    </div>
    <div class="metric-card">
      <div class="metric-label">Network I/O</div>
      <div class="metric-val">{rx} KB/s ↓</div>
      <div class="metric-sub">{tx} KB/s ↑</div>
    </div>
    <div class="metric-card">
      <div class="metric-label">Parallel Jobs</div>
      <div class="metric-val">{run.jobs ? run.jobs.length : 0}</div>
      <div class="metric-sub">{run.is_default_branch ? 'Default Branch (ci-* & cd-*)' : 'Feature Branch (ci-* only)'}</div>
    </div>
  </div>

  {#if run.jobs && run.jobs.length}
    <div class="job-tabs">
      {#each run.jobs as j (j.name)}
        <button
          class="job-tab"
          class:active={selectedJob === j.name}
          onclick={() => { selectedJob = j.name; setupStream(); }}
        >
          <span class="status-dot small {j.status}"></span>
          <span class="job-title">{j.name}</span>
          {#if j.exit_code !== null}
            <span class="job-code" class:bad={j.exit_code !== 0}>[{j.exit_code}]</span>
          {/if}
        </button>
      {/each}
      <button
        class="job-tab"
        class:active={selectedJob === ''}
        onclick={() => { selectedJob = ''; setupStream(); }}
      >
        <span>All Combined Logs</span>
      </button>
    </div>
  {/if}

  <div class="terminal-box">
    <div class="term-bar">
      <div class="term-title">Console Output: {selectedJob || 'All Jobs'}</div>
      <div class="term-controls">
        <input type="text" placeholder="Search logs…" bind:value={search} class="term-search" />
        <label class="term-check">
          <input type="checkbox" bind:checked={autoscroll} />
          Auto-scroll
        </label>
      </div>
    </div>
    <pre bind:this={terminalEl} class="term-body">{filteredLogs || 'Waiting for runner process output…'}</pre>
  </div>
{/if}

<style>
  .run-header { display: flex; justify-content: space-between; align-items: flex-start; gap: 1.5rem; margin-bottom: 1.5rem; }
  .crumbs { font-size: 0.85rem; color: var(--muted, #94a3b8); margin-bottom: 0.4rem; }
  .crumbs a { color: #38bdf8; text-decoration: none; }
  h1 { font-size: 1.5rem; margin: 0 0 0.4rem; display: flex; align-items: center; gap: 0.6rem; }
  h1 code { background: rgba(255,255,255,0.06); padding: 0.15rem 0.4rem; border-radius: 4px; font-size: 1.2rem; color: #38bdf8; }
  .status-dot { width: 12px; height: 12px; border-radius: 50%; display: inline-block; flex-shrink: 0; }
  .status-dot.small { width: 8px; height: 8px; }
  .status-dot.in_progress { background: #facc15; box-shadow: 0 0 8px #facc15; }
  .status-dot.success { background: #4ade80; box-shadow: 0 0 8px #4ade80; }
  .status-dot.failure, .status-dot.crash { background: #f87171; box-shadow: 0 0 8px #f87171; }
  .status-dot.pending { background: #94a3b8; }
  .commit-desc { color: #cbd5e1; font-size: 0.95rem; margin: 0 0 0.6rem; }
  .details-row { display: flex; gap: 1.2rem; font-size: 0.85rem; color: var(--muted, #94a3b8); }
  .details-row strong { color: #f8fafc; }
  .actions-col { display: flex; gap: 0.7rem; }
  .btn { padding: 0.5rem 1rem; border-radius: 6px; font-weight: 600; cursor: pointer; text-decoration: none; font-size: 0.88rem; border: 1px solid transparent; }
  .btn.ok { background: #22c55e; color: #fff; }
  .btn.ok:hover { background: #16a34a; }
  .btn.outline { background: transparent; border-color: var(--border, #334155); color: #cbd5e1; }
  .btn.outline:hover { background: rgba(255,255,255,0.05); }
  .telemetry-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(190px, 1fr)); gap: 1rem; margin-bottom: 1.5rem; }
  .metric-card { background: var(--panel, #111827); border: 1px solid var(--border, #1e293b); border-radius: 8px; padding: 1rem; }
  .metric-label { font-size: 0.75rem; text-transform: uppercase; letter-spacing: 0.06em; color: var(--muted, #94a3b8); font-weight: 600; margin-bottom: 0.3rem; }
  .metric-val { font-size: 1.5rem; font-weight: 700; color: #f8fafc; }
  .metric-sub { font-size: 0.8rem; color: #64748b; margin-top: 0.2rem; }
  .job-tabs { display: flex; gap: 0.5rem; margin-bottom: 0.8rem; overflow-x: auto; padding-bottom: 0.2rem; }
  .job-tab { display: inline-flex; align-items: center; gap: 0.5rem; padding: 0.45rem 0.85rem; border-radius: 6px; border: 1px solid var(--border, #334155); background: var(--panel, #111827); color: #cbd5e1; font-size: 0.85rem; font-weight: 600; cursor: pointer; }
  .job-tab:hover { background: rgba(255,255,255,0.06); color: #fff; }
  .job-tab.active { background: color-mix(in srgb, var(--accent, #3b82f6) 20%, transparent); border-color: var(--accent, #3b82f6); color: #38bdf8; }
  .job-code.bad { color: #f87171; }
  .terminal-box { background: #000; border: 1px solid var(--border, #1e293b); border-radius: 8px; overflow: hidden; }
  .term-bar { display: flex; justify-content: space-between; align-items: center; background: #0f172a; padding: 0.6rem 1rem; border-bottom: 1px solid #1e293b; font-size: 0.85rem; }
  .term-title { font-weight: 600; color: #94a3b8; }
  .term-controls { display: flex; align-items: center; gap: 1rem; }
  .term-search { background: #1e293b; border: 1px solid #334155; color: #fff; padding: 0.25rem 0.6rem; border-radius: 4px; font-size: 0.8rem; }
  .term-check { display: flex; align-items: center; gap: 0.35rem; color: #94a3b8; font-size: 0.8rem; cursor: pointer; }
  .term-body { margin: 0; padding: 1rem; height: 520px; overflow-y: auto; font-family: 'JetBrains Mono', monospace; font-size: 0.85rem; line-height: 1.5; color: #e2e8f0; white-space: pre-wrap; word-break: break-all; }
</style>
