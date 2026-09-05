<script>
  import { admin } from '$lib/api.js';
  import { resource } from '$lib/resource.svelte.js';
  import { refreshOn } from '$lib/events.js';
  import { onMount } from 'svelte';
  import { when, usd } from '$lib/format.js';
  import Panel from '$lib/components/Panel.svelte';
  import Loader from '$lib/components/Loader.svelte';
  import Badge from '$lib/components/Badge.svelte';
  import Confirm from '$lib/components/Confirm.svelte';

  const creds = resource(() => admin.get('/credentials'));
  onMount(() => refreshOn(['credential.*'], () => creds.reload()));

  let kind = $state('oauth');
  let secret = $state('');
  let label = $state('');
  let busy = $state(false);
  let error = $state('');

  async function run(fn) {
    busy = true;
    error = '';
    try {
      await fn();
      await creds.reload();
    } catch (e) {
      error = e.message;
    } finally {
      busy = false;
    }
  }

  const add = () => run(async () => {
    await admin.post('/credentials', { kind, secret: secret.trim(), label: label.trim() || null });
    secret = '';
    label = '';
  });

  const keyState = (c) =>
    !c.enabled ? ['bad', 'disabled']
    : c.cooldown_until && new Date(c.cooldown_until) > new Date() ? ['warn', 'cooldown']
    : ['ok', 'ready'];
</script>

<svelte:head><title>unsafie — keys</title></svelte:head>
<h1>Anthropic keys</h1>

<div class="stack">
  <Panel title="Add a key">
    <div class="row pad">
      <select bind:value={kind} disabled={busy}>
        <option value="oauth">oauth</option>
        <option value="api_key">api_key</option>
      </select>
      <input class="grow" type="password" placeholder="secret" bind:value={secret} disabled={busy} />
      <input placeholder="label" bind:value={label} disabled={busy} />
      <button onclick={add} disabled={busy || !secret.trim()}>Add</button>
    </div>
    {#if error}<p class="pad err">{error}</p>{/if}
  </Panel>

  <Panel title="Keys">
    <Loader state={creds} empty="No keys — the bot cannot answer anything.">
      <table>
        <thead>
          <tr><th>id</th><th>kind</th><th>secret</th><th>label</th><th>state</th><th>uses</th><th>spent</th><th>last error</th><th></th></tr>
        </thead>
        <tbody>
          {#each creds.data as c (c.id)}
            {@const [tone, word] = keyState(c)}
            <tr>
              <td class="mono">{c.id}</td>
              <td>{c.kind}</td>
              <td class="mono muted">{c.secret_masked}</td>
              <td>{c.label ?? '—'}</td>
              <td>
                <Badge {tone}>{word}</Badge>
                {#if c.failures}<span class="muted small"> {c.failures}✕</span>{/if}
                {#if c.cooldown_until}<div class="muted small">till {when(c.cooldown_until)}</div>{/if}
              </td>
              <td>{c.uses}</td>
              <td>{usd(c.total_cost_usd)}</td>
              <td class="err small">{c.last_error ? c.last_error.slice(0, 90) : ''}</td>
              <td class="row nowrap">
                <button disabled={busy} onclick={() => run(() => admin.patch(`/credentials/${c.id}`, { enabled: !c.enabled }))}>
                  {c.enabled ? 'Disable' : 'Enable'}
                </button>
                <button disabled={busy} onclick={() => run(() => admin.patch(`/credentials/${c.id}`, { reset: true }))}>Reset</button>
                <Confirm label="Delete" question="Delete key {c.id}?" onconfirm={() => run(() => admin.del(`/credentials/${c.id}`))} />
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
