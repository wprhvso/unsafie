<script>
  import { onMount } from 'svelte';
  import { admin } from '$lib/api.js';
  import { resource } from '$lib/resource.svelte.js';
  import { refreshOn } from '$lib/events.js';
  import { when, duration } from '$lib/format.js';
  import Panel from '$lib/components/Panel.svelte';
  import Loader from '$lib/components/Loader.svelte';
  import Pager from '$lib/components/Pager.svelte';
  import Badge from '$lib/components/Badge.svelte';
  import Confirm from '$lib/components/Confirm.svelte';

  let offset = $state(0);
  let result = $state('');
  const watches = resource(() => admin.get('/watches', { offset, limit: 50 }));
  const move = (n) => { offset = n; watches.reload(); };
  onMount(() => refreshOn(['watch.*'], () => watches.reload(), 2000));

  async function runNow(id) {
    result = '…';
    try {
      const r = await admin.post(`/watches/${id}/run`);
      result = `[${id}] ${r.detail}`;
    } catch (e) {
      result = `[${id}] ${e.message}`;
    }
    await watches.reload();
  }
</script>

<svelte:head><title>unsafie — watches</title></svelte:head>
<h1>Server checks</h1>

<Panel>
  {#snippet actions()}
    {#if result}<span class="small muted">{result}</span>{/if}
  {/snippet}

  <Loader state={watches} empty="No checks.">
    <table>
      <thead><tr><th>id</th><th>name</th><th>host</th><th>command</th><th>condition</th><th>every</th><th>state</th><th>last run</th><th></th></tr></thead>
      <tbody>
        {#each watches.data.items as w (w.id)}
          <tr>
            <td class="mono">{w.id}</td>
            <td>{w.name}</td>
            <td class="mono">{w.host}</td>
            <td class="mono small cmd">{w.command}</td>
            <td class="mono small">{w.condition}</td>
            <td class="small">{duration(w.interval_sec)}</td>
            <td>
              {#if !w.enabled}
                <Badge tone="warn">paused</Badge>
              {:else if w.alerting}
                <Badge tone="bad">alerting</Badge>
              {:else}
                <Badge tone="ok">ok</Badge>
              {/if}
              {#if w.fails}<span class="muted small"> {w.fails}✕</span>{/if}
            </td>
            <td class="muted small nowrap">{when(w.last_run_at)}{w.last_exit !== null ? ` · exit ${w.last_exit}` : ''}</td>
            <td class="row nowrap">
              <button onclick={() => runNow(w.id)}>Run</button>
              <button onclick={async () => { await admin.post(`/watches/${w.id}/pause?resume=${!w.enabled}`); await watches.reload(); }}>
                {w.enabled ? 'Pause' : 'Resume'}
              </button>
              <Confirm label="Delete" question="Delete check {w.id}?"
                onconfirm={async () => { await admin.del(`/watches/${w.id}`); await watches.reload(); }} />
            </td>
          </tr>
        {/each}
      </tbody>
    </table>
    <Pager total={watches.data.total} {offset} limit={watches.data.limit} onmove={move} />
  </Loader>
</Panel>

<style>.cmd { max-width: 18rem; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }</style>
