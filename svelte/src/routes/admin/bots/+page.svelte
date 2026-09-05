<script>
  import { admin } from '$lib/api.js';
  import { resource } from '$lib/resource.svelte.js';
  import Panel from '$lib/components/Panel.svelte';
  import Loader from '$lib/components/Loader.svelte';
  import Badge from '$lib/components/Badge.svelte';
  import Confirm from '$lib/components/Confirm.svelte';

  const bots = resource(() => admin.get('/bots'));
  let token = $state('');
  let busy = $state(false);
  let error = $state('');

  async function run(fn) {
    busy = true;
    error = '';
    try {
      await fn();
      await bots.reload();
    } catch (e) {
      error = e.message;
    } finally {
      busy = false;
    }
  }

  const add = () => run(async () => {
    await admin.post('/bots', { token: token.trim() });
    token = '';
  });
</script>

<svelte:head><title>unsafie — bots</title></svelte:head>
<h1>Bots</h1>

<div class="stack">
  <Panel title="Add a bot">
    <div class="row pad">
      <input class="grow" placeholder="123456:AA…" bind:value={token} disabled={busy} />
      <button onclick={add} disabled={busy || !token.trim()}>Add</button>
    </div>
    {#if error}<p class="pad err">{error}</p>{/if}
  </Panel>

  <Panel title="Running">
    <Loader state={bots} empty="No bots yet.">
      <table>
        <thead>
          <tr><th>id</th><th>token</th><th>username</th><th>chats</th><th>state</th><th></th></tr>
        </thead>
        <tbody>
          {#each bots.data as b (b.id)}
            <tr>
              <td class="mono">{b.id}</td>
              <td class="mono muted">{b.token_masked}</td>
              <td>{b.username ? `@${b.username}` : '—'}</td>
              <td>{b.chats}</td>
              <td>
                <Badge tone={b.running ? 'ok' : 'bad'}>{b.running ? 'running' : 'stopped'}</Badge>
              </td>
              <td class="row nowrap">
                <button disabled={busy} onclick={() => run(() => admin.post(`/bots/${b.id}/restart`))}>Restart</button>
                <Confirm label="Delete" question="Delete bot {b.id}?" onconfirm={() => run(() => admin.del(`/bots/${b.id}`))} />
              </td>
            </tr>
          {/each}
        </tbody>
      </table>
    </Loader>
  </Panel>
</div>

<style>
  .pad { padding: .8rem 1rem; }
  .err { color: var(--bad); margin: 0; }
</style>
