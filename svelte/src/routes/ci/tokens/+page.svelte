<script>
  import { onMount } from 'svelte';
  import { api } from '$lib/api.js';
  import { when } from '$lib/format.js';
  import Loader from '$lib/components/Loader.svelte';
  import Confirm from '$lib/components/Confirm.svelte';

  let tokens = $state([]);
  let loading = $state(true);
  let name = $state('');
  let busy = $state(false);
  let createdToken = $state(null);
  let copied = $state(false);

  async function loadTokens() {
    loading = true;
    try {
      tokens = await api.get('/api/ci/tokens') || [];
    } catch {
      tokens = [];
    } finally {
      loading = false;
    }
  }

  async function create() {
    if (!name.trim()) return;
    busy = true;
    try {
      const res = await api.post('/api/ci/tokens', { name: name.trim() });
      createdToken = res.token;
      name = '';
      await loadTokens();
    } catch {
    } finally {
      busy = false;
    }
  }

  async function remove(id) {
    await api.delete(`/api/ci/tokens/${id}`);
    await loadTokens();
  }

  function copyToken() {
    if (!createdToken) return;
    navigator.clipboard.writeText(createdToken);
    copied = true;
    setTimeout(() => { copied = false; }, 2500);
  }

  onMount(loadTokens);
</script>

<svelte:head><title>CI API Tokens — unsafie CI</title></svelte:head>

<div class="top">
  <h1>Personal CI API Tokens</h1>
  <p class="subtitle">Authenticate with <code>curl</code> and automation tools to manage secrets without the Web UI</p>
</div>

{#if createdToken}
  <div class="card token-alert">
    <h3>New API Token Created!</h3>
    <p class="warn-text">Make sure to copy this token now. You will not be able to view it again!</p>
    <div class="token-box">
      <code>{createdToken}</code>
      <button class="btn ok" onclick={copyToken}>
        {copied ? '✓ Copied!' : 'Copy Token'}
      </button>
    </div>
    <button class="btn-dismiss" onclick={() => { createdToken = null; }}>Dismiss</button>
  </div>
{/if}

<div class="card">
  <h3>Generate New Token</h3>
  <form onsubmit={(e) => { e.preventDefault(); create(); }} class="token-form">
    <input
      type="text"
      placeholder="Token description (e.g. Deployment Script, Mac Terminal)"
      bind:value={name}
      disabled={busy}
      required
    />
    <button class="btn primary" type="submit" disabled={busy || !name.trim()}>
      {busy ? 'Generating…' : 'Generate Token'}
    </button>
  </form>
</div>

<div class="card">
  <h3>Active Tokens</h3>
  {#if loading}
    <Loader />
  {:else if tokens.length}
    <table class="table">
      <thead>
        <tr>
          <th>Name</th>
          <th>Prefix</th>
          <th>Last Used</th>
          <th>Created</th>
          <th></th>
        </tr>
      </thead>
      <tbody>
        {#each tokens as item (item.id)}
          <tr>
            <td><strong>{item.name}</strong></td>
            <td><code>{item.prefix}</code></td>
            <td class="muted">{item.last_used_at ? when(item.last_used_at) : 'never'}</td>
            <td class="muted">{when(item.created_at)}</td>
            <td>
              <Confirm onconfirm={() => remove(item.id)}>
                <button class="btn-del">Revoke</button>
              </Confirm>
            </td>
          </tr>
        {/each}
      </tbody>
    </table>
  {:else}
    <p class="muted">You have no active API tokens.</p>
  {/if}
</div>

<div class="card guide-card">
  <h3>How to Use Tokens with <code>curl</code></h3>
  <p class="muted">Pass the generated token in the <code>Authorization: Bearer</code> header:</p>

  <div class="example">
    <span class="example-title">1. Bulk Upload <code>.env</code> file:</span>
    <pre class="code-box">curl -X PUT https://ci.unsafie.com/api/ci/secrets/owner/repo/bulk   -H "Authorization: Bearer uci_live_YOUR_TOKEN"   -H "Content-Type: text/plain"   --data-binary @.env.production</pre>
  </div>

  <div class="example">
    <span class="example-title">2. Set a Single Key:</span>
    <pre class="code-box">curl -X POST https://ci.unsafie.com/api/ci/secrets/owner/repo   -H "Authorization: Bearer uci_live_YOUR_TOKEN"   -H "Content-Type: application/json"   -d '&#123;"key": "PORT", "value": "8080"&#125;'</pre>
  </div>
</div>

<style>
  .top { margin-bottom: 1.5rem; }
  h1 { font-size: 1.6rem; margin: 0 0 0.2rem; }
  .subtitle { color: var(--muted, #94a3b8); font-size: 0.9rem; margin: 0; }
  .card { background: var(--panel, #111827); border: 1px solid var(--border, #1e293b); border-radius: 10px; padding: 1.2rem; margin-bottom: 1.2rem; }
  .token-alert { border-color: #facc15; background: rgba(250, 204, 21, 0.05); }
  .warn-text { color: #facc15; font-size: 0.88rem; margin: 0 0 0.8rem; }
  .token-box { display: flex; gap: 0.8rem; align-items: center; background: #000; padding: 0.7rem 1rem; border-radius: 6px; border: 1px solid var(--border, #334155); margin-bottom: 0.8rem; }
  .token-box code { color: #4ade80; font-family: monospace; font-size: 0.95rem; word-break: break-all; flex: 1; }
  .btn-dismiss { background: transparent; border: none; color: #94a3b8; font-size: 0.85rem; cursor: pointer; text-decoration: underline; padding: 0; }
  .token-form { display: flex; gap: 0.8rem; }
  .token-form input { flex: 1; padding: 0.6rem 0.8rem; border: 1px solid var(--border, #334155); border-radius: 6px; background: var(--bg, #0b0f17); color: #fff; font-size: 0.9rem; }
  .table { width: 100%; border-collapse: collapse; font-size: 0.88rem; }
  .table th, .table td { padding: 0.6rem 0.8rem; text-align: left; border-bottom: 1px solid var(--border, #1e293b); }
  .table code { color: #38bdf8; }
  .btn { padding: 0.5rem 1rem; border-radius: 6px; font-weight: 600; cursor: pointer; border: none; font-size: 0.88rem; }
  .btn.primary { background: #3b82f6; color: #fff; }
  .btn.ok { background: #22c55e; color: #fff; }
  .btn-del { background: transparent; border: 1px solid #ef4444; color: #f87171; border-radius: 4px; padding: 0.2rem 0.5rem; cursor: pointer; font-size: 0.75rem; }
  .btn-del:hover { background: rgba(239,68,68,0.15); }
  .muted { color: var(--muted, #94a3b8); font-size: 0.85rem; }
  .example { margin-top: 1rem; }
  .example-title { font-weight: 600; font-size: 0.85rem; color: #cbd5e1; display: block; margin-bottom: 0.3rem; }
  .code-box { background: #000; border: 1px solid var(--border, #1e293b); border-radius: 6px; padding: 0.8rem; font-family: monospace; font-size: 0.82rem; color: #e2e8f0; overflow-x: auto; margin: 0; }
</style>
