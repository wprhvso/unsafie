<script>
  import { page } from '$app/state';
  import { admin } from '$lib/api.js';
  import { resource } from '$lib/resource.svelte.js';
  import { money, when } from '$lib/format.js';
  import Panel from '$lib/components/Panel.svelte';
  import Loader from '$lib/components/Loader.svelte';

  const id = page.params.id;
  const user = resource(() => admin.get(`/users/${id}`));
  const txs = resource(() => admin.get(`/users/${id}/transactions`));
  const turns = resource(() => admin.get('/turns', { user_id: id, limit: 20 }));

  let amount = $state(10000);
  let budget = $state(-1);
  let busy = $state(false);
  let error = $state('');

  async function run(fn) {
    busy = true;
    error = '';
    try {
      await fn();
      await Promise.all([user.reload(), txs.reload()]);
    } catch (e) {
      error = e.message;
    } finally {
      busy = false;
    }
  }
</script>

<svelte:head><title>unsafie — user {id}</title></svelte:head>
<h1>User {id}</h1>

<div class="stack">
  <Loader state={user}>
    {@const u = user.data}
    <Panel title="Account">
      <div class="pad stack">
        <div class="row wide">
          <span><span class="muted">balance</span> <b>{money(u.balance)}</b></span>
          <span><span class="muted">per-turn budget</span> <b>{u.budget < 0 ? '∞' : money(u.budget)}</b></span>
          <span><span class="muted">locale</span> {u.locale ?? '—'}</span>
          <span><span class="muted">timezone</span> {u.timezone ?? '—'}</span>
          <span><span class="muted">git</span> {u.git_name ? `${u.git_name} <${u.git_email}>` : '—'}</span>
          <span><span class="muted">github</span> {u.github_logins.join(', ') || '—'}</span>
          <span><span class="muted">ssh key</span> {u.has_ssh_key ? 'yes' : 'no'}</span>
        </div>
        <div class="row">
          <input type="number" step="1000" bind:value={amount} disabled={busy} />
          <button onclick={() => run(() => admin.post(`/users/${id}/deposit`, { amount: Number(amount) }))} disabled={busy}>
            Deposit
          </button>
          <span class="muted small">= {money(amount)}</span>
        </div>
        <div class="row">
          <input type="number" step="100" bind:value={budget} disabled={busy} />
          <button onclick={() => run(() => admin.put(`/users/${id}/budget`, { budget: Number(budget) }))} disabled={busy}>
            Set budget
          </button>
          <span class="muted small">−1 for unlimited</span>
        </div>
        {#if error}<p class="err">{error}</p>{/if}
      </div>
    </Panel>
  </Loader>

  <Panel title="Transactions">
    <Loader state={txs} empty="No transactions.">
      <table>
        <thead><tr><th>id</th><th>kind</th><th>amount</th><th>when</th></tr></thead>
        <tbody>
          {#each txs.data as t (t.id)}
            <tr>
              <td class="mono">{t.id}</td>
              <td>{t.kind}</td>
              <td class:bad={t.amount < 0}>{money(t.amount)}</td>
              <td class="muted">{when(t.created_at)}</td>
            </tr>
          {/each}
        </tbody>
      </table>
    </Loader>
  </Panel>

  <Panel title="Recent turns">
    <Loader state={turns} empty="No turns.">
      <table>
        <thead><tr><th>id</th><th>chat</th><th>status</th><th>charge</th><th>when</th></tr></thead>
        <tbody>
          {#each turns.data.items as t (t.id)}
            <tr>
              <td class="mono"><a href="/admin/turns/{t.id}">{t.id.slice(0, 8)}</a></td>
              <td class="mono">{t.chat_id}</td>
              <td>{t.status}</td>
              <td>{money(t.charge)}</td>
              <td class="muted">{when(t.created_at)}</td>
            </tr>
          {/each}
        </tbody>
      </table>
    </Loader>
  </Panel>
</div>

<style>
  .pad { padding: 1rem; }
  .wide { gap: 1.4rem; }
  .bad { color: var(--bad); }
  .err { color: var(--bad); margin: 0; }
</style>
