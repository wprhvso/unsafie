<script>
  import { api } from '$lib/api.js';
  import { when } from '$lib/format.js';
  import Loader from '$lib/components/Loader.svelte';
  import Confirm from '$lib/components/Confirm.svelte';

  let repo = $state('');
  let secretsList = $state([]);
  let loading = $state(false);
  let key = $state('');
  let val = $state('');
  let bulkText = $state('');
  let busy = $state(false);
  let error = $state('');
  let successMsg = $state('');

  async function loadSecrets() {
    if (!repo.includes('/')) return;
    loading = true;
    error = '';
    const [owner, name] = repo.trim().split('/');
    try {
      secretsList = await api.get(`/api/ci/secrets/${owner}/${name}`) || [];
    } catch (e) {
      secretsList = [];
      error = e.message;
    } finally {
      loading = false;
    }
  }

  async function saveSingle() {
    if (!repo.includes('/') || !key.trim()) return;
    busy = true;
    error = '';
    const [owner, name] = repo.trim().split('/');
    try {
      await api.post(`/api/ci/secrets/${owner}/${name}`, { key: key.trim(), value: val });
      key = '';
      val = '';
      successMsg = 'Secret saved!';
      setTimeout(() => { successMsg = ''; }, 3000);
      await loadSecrets();
    } catch (e) {
      error = e.message;
    } finally {
      busy = false;
    }
  }

  async function saveBulk() {
    if (!repo.includes('/') || !bulkText.trim()) return;
    busy = true;
    error = '';
    const [owner, name] = repo.trim().split('/');
    try {
      await api.put(`/api/ci/secrets/${owner}/${name}/bulk`, bulkText);
      bulkText = '';
      successMsg = 'Secrets imported!';
      setTimeout(() => { successMsg = ''; }, 3000);
      await loadSecrets();
    } catch (e) {
      error = e.message;
    } finally {
      busy = false;
    }
  }

  async function remove(secKey) {
    if (!repo.includes('/')) return;
    const [owner, name] = repo.trim().split('/');
    await api.delete(`/api/ci/secrets/${owner}/${name}/${secKey}`);
    await loadSecrets();
  }
</script>

<svelte:head><title>CD Secrets — unsafie CI</title></svelte:head>

<div class="top">
  <h1>Repository CD Secrets</h1>
  <p class="subtitle">Environment variables securely injected exclusively during the <code>cd</code> stage on the <code>main</code> branch</p>
</div>

<div class="repo-selector card">
  <label for="repo-input"><strong>Select Repository:</strong></label>
  <div class="repo-row">
    <input
      id="repo-input"
      type="text"
      placeholder="owner/repo (e.g. wprhvso/my-service)"
      bind:value={repo}
      onkeydown={(e) => { if (e.key === 'Enter') loadSecrets(); }}
    />
    <button class="btn primary" onclick={loadSecrets} disabled={!repo.includes('/') || loading}>
      {loading ? 'Loading…' : 'Load Secrets'}
    </button>
  </div>
</div>

{#if repo.includes('/')}
  {#if error}
    <div class="alert bad">{error}</div>
  {/if}
  {#if successMsg}
    <div class="alert ok">{successMsg}</div>
  {/if}

  <div class="grid">
    <div class="card">
      <h3>Active Secrets for {repo}</h3>
      {#if loading}
        <Loader />
      {:else if secretsList.length}
        <table class="table">
          <thead>
            <tr>
              <th>Key Name</th>
              <th>Updated By</th>
              <th>Updated</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {#each secretsList as item (item.key)}
              <tr>
                <td><code>{item.key}</code></td>
                <td>@{item.updated_by}</td>
                <td class="muted">{when(item.updated_at)}</td>
                <td>
                  <Confirm onconfirm={() => remove(item.key)}>
                    <button class="btn-del">Delete</button>
                  </Confirm>
                </td>
              </tr>
            {/each}
          </tbody>
        </table>
      {:else}
        <p class="muted">No secrets configured for this repository yet.</p>
      {/if}
    </div>

    <div class="forms-col">
      <div class="card">
        <h3>Add / Update Secret</h3>
        <form onsubmit={(e) => { e.preventDefault(); saveSingle(); }} class="form">
          <input type="text" placeholder="KEY (e.g. DOCKER_PASSWORD)" bind:value={key} required />
          <textarea rows="3" placeholder="Secret value…" bind:value={val} required></textarea>
          <button class="btn ok" type="submit" disabled={busy || !key.trim()}>Save Secret</button>
        </form>
      </div>

      <div class="card">
        <h3>Bulk Import .env</h3>
        <form onsubmit={(e) => { e.preventDefault(); saveBulk(); }} class="form">
          <textarea rows="5" placeholder="Paste full .env file here (KEY=VALUE)..." bind:value={bulkText} required></textarea>
          <button class="btn primary" type="submit" disabled={busy || !bulkText.trim()}>Import All Secrets</button>
        </form>
      </div>
    </div>
  </div>

  <div class="card curl-card">
    <h3>Managing Secrets via <code>curl</code> API</h3>
    <p class="muted">You can update secrets directly from your terminal or CI scripts using your API Bearer token:</p>
    <pre class="code-box">curl -X PUT https://ci.unsafie.com/api/ci/secrets/{repo}/bulk   -H "Authorization: Bearer uci_live_YOUR_TOKEN"   -H "Content-Type: text/plain"   --data-binary @.env.production</pre>
  </div>
{/if}

<style>
  .top { margin-bottom: 1.5rem; }
  h1 { font-size: 1.6rem; margin: 0 0 0.2rem; }
  .subtitle { color: var(--muted, #94a3b8); font-size: 0.9rem; margin: 0; }
  .card { background: var(--panel, #111827); border: 1px solid var(--border, #1e293b); border-radius: 10px; padding: 1.2rem; margin-bottom: 1.2rem; }
  .repo-row { display: flex; gap: 0.8rem; margin-top: 0.5rem; }
  .repo-row input { flex: 1; padding: 0.6rem 0.9rem; border: 1px solid var(--border, #334155); border-radius: 6px; background: var(--bg, #0b0f17); color: #fff; font-size: 0.95rem; }
  .grid { display: grid; grid-template-columns: 3fr 2fr; gap: 1.2rem; }
  .forms-col { display: flex; flex-direction: column; gap: 1.2rem; }
  h3 { margin: 0 0 1rem; font-size: 1.1rem; }
  .form { display: flex; flex-direction: column; gap: 0.7rem; }
  .form input, .form textarea { padding: 0.5rem 0.8rem; border: 1px solid var(--border, #334155); border-radius: 6px; background: var(--bg, #0b0f17); color: #fff; font-family: monospace; font-size: 0.88rem; }
  .table { width: 100%; border-collapse: collapse; font-size: 0.88rem; }
  .table th, .table td { padding: 0.6rem 0.8rem; text-align: left; border-bottom: 1px solid var(--border, #1e293b); }
  .table code { color: #38bdf8; font-weight: 600; }
  .btn { padding: 0.5rem 1rem; border-radius: 6px; font-weight: 600; cursor: pointer; border: none; font-size: 0.88rem; }
  .btn.primary { background: #3b82f6; color: #fff; }
  .btn.ok { background: #22c55e; color: #fff; }
  .btn-del { background: transparent; border: 1px solid #ef4444; color: #f87171; border-radius: 4px; padding: 0.2rem 0.5rem; cursor: pointer; font-size: 0.75rem; }
  .btn-del:hover { background: rgba(239,68,68,0.15); }
  .alert { padding: 0.75rem 1rem; border-radius: 8px; margin-bottom: 1.2rem; font-size: 0.9rem; }
  .alert.ok { background: rgba(74, 222, 128, 0.15); color: #4ade80; border: 1px solid #4ade80; }
  .alert.bad { background: rgba(248, 113, 113, 0.15); color: #f87171; border: 1px solid #f87171; }
  .muted { color: var(--muted, #94a3b8); font-size: 0.85rem; }
  .code-box { background: #000; border: 1px solid var(--border, #1e293b); border-radius: 6px; padding: 0.8rem; font-family: monospace; font-size: 0.82rem; color: #e2e8f0; overflow-x: auto; }
</style>
