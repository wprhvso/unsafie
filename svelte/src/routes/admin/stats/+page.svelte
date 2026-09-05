<script>
  import { admin } from '$lib/api.js';
  import { resource } from '$lib/resource.svelte.js';
  import { usd, money } from '$lib/format.js';
  import Panel from '$lib/components/Panel.svelte';
  import Loader from '$lib/components/Loader.svelte';

  let days = $state(30);
  let hours = $state(168);
  const daily = resource(() => admin.get('/stats/daily', { days }));
  const top = resource(() => admin.get('/stats/top-chats', { hours, limit: 20 }));
  const byKey = resource(() => admin.get('/stats/by-credential', { hours }));

  const max = $derived(Math.max(1, ...(daily.data ?? []).map((d) => d.cost_usd)));
  const total = $derived((daily.data ?? []).reduce((a, d) => a + d.cost_usd, 0));
</script>

<svelte:head><title>unsafie — stats</title></svelte:head>
<h1>Stats</h1>

<div class="stack">
  <Panel title="Daily spend">
    {#snippet actions()}
      <select bind:value={days} onchange={() => daily.reload()}>
        {#each [7, 30, 90, 365] as d (d)}<option value={d}>{d} days</option>{/each}
      </select>
    {/snippet}
    <Loader state={daily} empty="No activity.">
      <div class="chart">
        {#each daily.data as d (d.day)}
          <div class="bar" title="{d.day}: {usd(d.cost_usd)} · {d.turns} turns · charged {money(d.charge)}">
            <div class="fill" style="height: {Math.max(2, (d.cost_usd / max) * 100)}%"></div>
          </div>
        {/each}
      </div>
      <p class="muted small pad">Total for the period: {usd(total)}</p>
    </Loader>
  </Panel>

  <div class="cols">
    <Panel title="Top chats">
      {#snippet actions()}
        <select bind:value={hours} onchange={() => { top.reload(); byKey.reload(); }}>
          {#each [24, 168, 720] as h (h)}<option value={h}>{h}h</option>{/each}
        </select>
      {/snippet}
      <Loader state={top} empty="No activity.">
        <table>
          <thead><tr><th>chat</th><th>turns</th><th>cost</th></tr></thead>
          <tbody>
            {#each top.data as t (`${t.bot_id}-${t.chat_id}`)}
              <tr>
                <td class="mono"><a href="/admin/chats/{t.bot_id}/{t.chat_id}">{t.chat_id}</a></td>
                <td>{t.turns}</td>
                <td>{usd(t.cost_usd)}</td>
              </tr>
            {/each}
          </tbody>
        </table>
      </Loader>
    </Panel>

    <Panel title="By key">
      <Loader state={byKey} empty="No activity.">
        <table>
          <thead><tr><th>key</th><th>turns</th><th>cost</th></tr></thead>
          <tbody>
            {#each byKey.data as k (k.credential_id ?? 'none')}
              <tr>
                <td class="mono">{k.credential_id ?? '—'}</td>
                <td>{k.turns}</td>
                <td>{usd(k.cost_usd)}</td>
              </tr>
            {/each}
          </tbody>
        </table>
      </Loader>
    </Panel>
  </div>
</div>

<style>
  .chart { display: flex; align-items: flex-end; gap: 2px; height: 11rem; padding: 1rem; }
  .bar { flex: 1; height: 100%; display: flex; align-items: flex-end; }
  .fill { width: 100%; background: var(--accent); border-radius: 2px 2px 0 0; opacity: .75; }
  .bar:hover .fill { opacity: 1; }
  .pad { padding: 0 1rem 1rem; margin: 0; }
  .cols { display: grid; grid-template-columns: 1fr 1fr; gap: 1rem; }
  @media (max-width: 900px) { .cols { grid-template-columns: 1fr; } }
</style>
