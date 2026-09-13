<script>
  import { admin } from '$lib/api.js';
  import { resource } from '$lib/resource.svelte.js';
  import { when } from '$lib/format.js';
  import Panel from '$lib/components/Panel.svelte';
  import Loader from '$lib/components/Loader.svelte';
  import Badge from '$lib/components/Badge.svelte';
  import Confirm from '$lib/components/Confirm.svelte';

  const overview = resource(() => admin.get('/ci/overview'));
  const list = resource(() => admin.get('/ci/whitelist'));

  let login = $state('');
  let busy = $state(false);
  let error = $state('');

  async function run(fn) {
    busy = true;
    error = '';
    try {
      await fn();
      await list.reload();
      await overview.reload();
    } catch (e) {
      error = e.message;
    } finally {
      busy = false;
    }
  }

  const add = () => run(async () => {
    if (!login.trim()) return;
    await admin.post('/ci/whitelist', { login: login.trim() });
    login = '';
  });

  const drop = (user) => run(async () => {
    await admin.delete(`/ci/whitelist/${user}`);
  });
</script>

<svelte:head><title>unsafie — CI/CD Whitelist</title></svelte:head>

<div class="header">
  <h2>Native CI/CD Automation</h2>
  <a href="/ci" class="btn" target="_blank" rel="noreferrer">Open ci.unsafie.com ↗</a>
</div>

{#if overview.loading && !overview.current}
  <Loader />
{:else if overview.current}
  <div class="grid">
    <Panel title="Total Runs">
      <div class="metric">{overview.current.total}</div>
    </Panel>
    <Panel title="Running / Pending">
      <div class="metric warn">{overview.current.in_progress} / {overview.current.pending}</div>
    </Panel>
    <Panel title="Successful">
      <div class="metric ok">{overview.current.success}</div>
    </Panel>
    <Panel title="Failed / Crashed">
      <div class="metric bad">{overview.current.failure}</div>
    </Panel>
  </div>
{/if}

<Panel title="Add GitHub User to Whitelist">
  <form onsubmit={(e) => { e.preventDefault(); add(); }} class="add-form">
    <input
      type="text"
      placeholder="GitHub username (e.g. torvalds)"
      bind:value={login}
      disabled={busy}
      required
    />
    <button class="btn ok" type="submit" disabled={busy || !login.trim()}>
      {busy ? 'Adding…' : 'Add to Whitelist'}
    </button>
  </form>
  {#if error}
    <p class="error">{error}</p>
  {/if}
</Panel>

<Panel title="Trusted GitHub Whitelist (Root Execution Allowed)">
  {#if list.loading && !list.current}
    <Loader />
  {:else if list.current && list.current.length}
    <table class="table">
      <thead>
        <tr>
          <th>GitHub Login</th>
          <th>Added By</th>
          <th>Added Date</th>
          <th>Actions</th>
        </tr>
      </thead>
      <tbody>
        {#each list.current as item (item.github_login)}
          <tr>
            <td>
              <a href="https://github.com/{item.github_login}" target="_blank" rel="noreferrer" class="gh-user">
                @{item.github_login}
              </a>
            </td>
            <td><Badge text={item.added_by} /></td>
            <td class="muted">{when(item.created_at)}</td>
            <td>
              <Confirm onconfirm={() => drop(item.github_login)}>
                <button class="btn bad small">Remove</button>
              </Confirm>
            </td>
          </tr>
        {/each}
      </tbody>
    </table>
  {:else}
    <p class="muted">Whitelist is currently empty. Add users above to allow CI/CD root execution.</p>
  {/if}
</Panel>

<style>
  .header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 1.2rem; }
  .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 1rem; margin-bottom: 1.5rem; }
  .metric { font-size: 2rem; font-weight: 700; color: var(--text); }
  .metric.ok { color: var(--ok, #4ade80); }
  .metric.warn { color: var(--warn, #facc15); }
  .metric.bad { color: var(--bad, #f87171); }
  .add-form { display: flex; gap: 0.8rem; align-items: center; }
  .add-form input { flex: 1; padding: 0.5rem 0.8rem; border: 1px solid var(--border); border-radius: 6px; background: var(--bg); color: var(--text); }
  .btn { padding: 0.5rem 1rem; border-radius: 6px; font-weight: 600; cursor: pointer; border: 1px solid var(--border); background: var(--panel); color: var(--text); text-decoration: none; }
  .btn.ok { background: color-mix(in srgb, var(--ok, #4ade80) 20%, transparent); color: var(--ok, #4ade80); border-color: var(--ok, #4ade80); }
  .btn.bad { background: color-mix(in srgb, var(--bad, #f87171) 20%, transparent); color: var(--bad, #f87171); border-color: var(--bad, #f87171); }
  .btn.small { padding: 0.25rem 0.6rem; font-size: 0.8rem; }
  .table { width: 100%; border-collapse: collapse; }
  .table th, .table td { padding: 0.6rem 0.8rem; text-align: left; border-bottom: 1px solid var(--border); }
  .gh-user { color: var(--accent, #60a5fa); text-decoration: none; font-weight: 600; }
  .gh-user:hover { text-decoration: underline; }
  .muted { color: var(--muted, #94a3b8); font-size: 0.85rem; }
  .error { color: var(--bad, #f87171); margin-top: 0.5rem; font-size: 0.9rem; }
</style>
