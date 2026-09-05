<script>
  import { onMount } from 'svelte';
  import { admin } from '$lib/api.js';
  import { resource } from '$lib/resource.svelte.js';
  import { refreshOn } from '$lib/events.js';
  import { when } from '$lib/format.js';
  import Panel from '$lib/components/Panel.svelte';
  import Loader from '$lib/components/Loader.svelte';
  import Pager from '$lib/components/Pager.svelte';
  import Badge from '$lib/components/Badge.svelte';
  import Json from '$lib/components/Json.svelte';

  let offset = $state(0);
  let errorsOnly = $state(false);
  let selected = $state(null);
  const list = resource(() => admin.get('/deliveries', { offset, limit: 50, errors_only: errorsOnly }));
  const move = (n) => { offset = n; list.reload(); };
  onMount(() => refreshOn(['webhook.*'], () => list.reload(), 2000));

  async function open(id) {
    selected = selected?.delivery_id === id ? null : await admin.get(`/deliveries/${id}`);
  }
</script>

<svelte:head><title>unsafie — deliveries</title></svelte:head>
<h1>Webhook deliveries</h1>

<Panel>
  {#snippet actions()}
    <label class="row small muted">
      <input type="checkbox" bind:checked={errorsOnly} onchange={() => move(0)} /> errors only
    </label>
    <button onclick={async () => { await admin.post('/deliveries/purge'); await list.reload(); }}>Purge old</button>
  {/snippet}

  <Loader state={list} empty="No deliveries yet.">
    <table>
      <thead><tr><th>event</th><th>repository</th><th>sender</th><th>state</th><th>sent</th><th>received</th></tr></thead>
      <tbody>
        {#each list.data.items as d (d.delivery_id)}
          <tr class="clickable" onclick={() => open(d.delivery_id)}>
            <td>{d.event}{d.action ? `.${d.action}` : ''}</td>
            <td>{d.repo_full_name ?? '—'}</td>
            <td class="muted">{d.sender ?? '—'}</td>
            <td>
              {#if d.error}
                <Badge tone="bad">error</Badge>
              {:else if d.processed_at}
                <Badge tone="ok">done</Badge>
              {:else}
                <Badge tone="warn">pending</Badge>
              {/if}
            </td>
            <td>{d.notified}</td>
            <td class="muted small nowrap">{when(d.received_at)}</td>
          </tr>
          {#if d.error}
            <tr><td colspan="6" class="err small">{d.error}</td></tr>
          {/if}
          {#if selected?.delivery_id === d.delivery_id}
            <tr><td colspan="6"><Json value={selected.payload} open /></td></tr>
          {/if}
        {/each}
      </tbody>
    </table>
    <Pager total={list.data.total} {offset} limit={list.data.limit} onmove={move} />
  </Loader>
</Panel>

<style>
  .clickable { cursor: pointer; }
  .err { color: var(--bad); }
</style>
