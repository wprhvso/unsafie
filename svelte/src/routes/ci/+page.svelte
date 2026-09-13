<script>
  import { onMount } from 'svelte';
  import { api } from '$lib/api.js';
  import { when } from '$lib/format.js';
  import Loader from '$lib/components/Loader.svelte';

  let runs = $state([]);
  let loading = $state(true);
  let repoFilter = $state('');

  async function load() {
    try {
      const url = repoFilter ? `/api/ci/runs?repo=${encodeURIComponent(repoFilter)}` : '/api/ci/runs';
      runs = await api.get(url) || [];
    } catch {
      runs = [];
    } finally {
      loading = false;
    }
  }

  onMount(() => {
    load();
    const timer = setInterval(load, 5000);
    return () => clearInterval(timer);
  });

  const statusClass = (s) =>
    s === 'success' ? 'ok'
    : s === 'in_progress' ? 'warn'
    : s === 'pending' ? 'muted'
    : 'bad';
</script>

<svelte:head><title>CI/CD Pipelines — unsafie.com</title></svelte:head>

<div class="dash-top">
  <div>
    <h1>Pipelines & Workflows</h1>
    <p class="subtitle">Root-level high-performance CI/CD for all connected repositories</p>
  </div>
  <div class="filter-box">
    <input
      type="text"
      placeholder="Filter by repo (owner/repo)…"
      bind:value={repoFilter}
      oninput={load}
    />
  </div>
</div>

{#if loading && !runs.length}
  <Loader />
{:else if runs.length}
  <div class="card">
    <table class="table">
      <thead>
        <tr>
          <th>Status</th>
          <th>Repository</th>
          <th>Commit & Message</th>
          <th>Branch</th>
          <th>Trigger</th>
          <th>Time</th>
          <th></th>
        </tr>
      </thead>
      <tbody>
        {#each runs as run (run.id)}
          <tr>
            <td>
              <span class="badge {statusClass(run.status)}">
                {run.status === 'in_progress' ? '● running' : run.status}
              </span>
            </td>
            <td>
              <strong>{run.repo_full_name}</strong>
            </td>
            <td>
              <div class="commit-cell">
                <code>{run.commit_sha.slice(0, 7)}</code>
                <span class="commit-msg">{run.commit_message || 'Commit'}</span>
              </div>
            </td>
            <td>
              <span class="branch-tag" class:default={run.is_default_branch}>
                {run.branch}
              </span>
            </td>
            <td>
              <span class="muted">{run.trigger_event}</span>
            </td>
            <td>
              <span class="muted">{when(run.created_at)}</span>
            </td>
            <td>
              <a href="/ci/runs/{run.id}" class="view-btn">View Details →</a>
            </td>
          </tr>
        {/each}
      </tbody>
    </table>
  </div>
{:else}
  <div class="empty">
    <p>No workflow runs recorded yet.</p>
    <p class="muted">Push to any repository with a <code>justfile</code> or <code>Makefile</code> to start a build.</p>
    <a href="/ci/docs" class="btn-guide">Read Integration Guide →</a>
  </div>
{/if}

<style>
  .dash-top { display: flex; justify-content: space-between; align-items: flex-end; margin-bottom: 1.5rem; gap: 1rem; }
  h1 { font-size: 1.6rem; font-weight: 700; margin: 0 0 0.2rem; }
  .subtitle { color: var(--muted, #94a3b8); font-size: 0.9rem; margin: 0; }
  .filter-box input { padding: 0.5rem 0.8rem; border: 1px solid var(--border, #334155); border-radius: 6px; background: var(--panel, #111827); color: #f8fafc; font-size: 0.88rem; width: 260px; }
  .card { background: var(--panel, #111827); border: 1px solid var(--border, #1e293b); border-radius: 10px; overflow: hidden; }
  .table { width: 100%; border-collapse: collapse; text-align: left; font-size: 0.9rem; }
  .table th { padding: 0.8rem 1rem; border-bottom: 1px solid var(--border, #1e293b); color: var(--muted, #94a3b8); font-weight: 600; font-size: 0.8rem; text-transform: uppercase; letter-spacing: 0.05em; }
  .table td { padding: 0.85rem 1rem; border-bottom: 1px solid rgba(255,255,255,0.04); vertical-align: middle; }
  .badge { padding: 0.2rem 0.55rem; border-radius: 4px; font-size: 0.75rem; font-weight: 700; text-transform: uppercase; }
  .badge.ok { background: rgba(74, 222, 128, 0.15); color: #4ade80; }
  .badge.warn { background: rgba(250, 204, 21, 0.15); color: #facc15; }
  .badge.bad { background: rgba(248, 113, 113, 0.15); color: #f87171; }
  .badge.muted { background: rgba(148, 163, 184, 0.15); color: #94a3b8; }
  .commit-cell { display: flex; align-items: center; gap: 0.5rem; }
  .commit-cell code { background: rgba(255,255,255,0.06); padding: 0.15rem 0.4rem; border-radius: 4px; color: #38bdf8; font-family: monospace; font-size: 0.85rem; }
  .commit-msg { max-width: 320px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; color: #cbd5e1; }
  .branch-tag { background: rgba(255,255,255,0.05); padding: 0.15rem 0.45rem; border-radius: 4px; font-size: 0.8rem; font-family: monospace; }
  .branch-tag.default { border-left: 3px solid #3b82f6; }
  .view-btn { color: #38bdf8; text-decoration: none; font-weight: 600; font-size: 0.85rem; }
  .view-btn:hover { text-decoration: underline; }
  .empty { padding: 4rem 2rem; text-align: center; background: var(--panel, #111827); border-radius: 10px; border: 1px solid var(--border, #1e293b); }
  .btn-guide { display: inline-block; margin-top: 1rem; background: #3b82f6; color: #fff; padding: 0.5rem 1rem; border-radius: 6px; text-decoration: none; font-weight: 600; font-size: 0.9rem; }
  .muted { color: var(--muted, #94a3b8); font-size: 0.85rem; }
</style>
