<script>
  import { onMount } from 'svelte';
  import { admin } from '$lib/api.js';
  import { resource } from '$lib/resource.svelte.js';
  import { refreshOn } from '$lib/events.js';
  import { money, usd } from '$lib/format.js';
  import Panel from '$lib/components/Panel.svelte';
  import Loader from '$lib/components/Loader.svelte';
  import Stat from '$lib/components/Stat.svelte';
  import Live from '$lib/components/Live.svelte';

  const overview = resource(() => admin.get('/overview'));
  onMount(() => refreshOn(['turn.*', 'webhook.*', 'watch.*', 'bot.*'], () => overview.reload(), 3000));

  const max = $derived(Math.max(1, ...(overview.data?.daily ?? []).map((d) => d.cost_usd)));
</script>

<svelte:head><title>unsafie — overview</title></svelte:head>

<h1>Overview</h1>

<Loader state={overview}>
  {@const o = overview.data}
  <div class="grid">
    <Stat label="Bots" value="{o.bots_running}/{o.bots}" hint="running" tone={o.bots_running < o.bots ? 'warn' : ''} />
    <Stat label="Users" value={o.users} hint="{o.chats} chats" />
    <Stat label="Turns 24h" value={o.day.turns} hint="{o.day.failed} failed" tone={o.day.failed ? 'warn' : ''} />
    <Stat label="Spend 24h" value={usd(o.day.cost_usd)} hint="charged {money(o.day.charge)}" />
    <Stat label="Running" value={o.running_turns} hint="turns in flight" />
    <Stat label="Keys" value="{o.credentials}/{o.credentials_total}" hint="usable" tone={o.credentials ? '' : 'bad'} />
    <Stat label="Repos" value={o.repos} hint="{o.installations} installations" />
    <Stat label="Watches" value={o.watches} hint="{o.watches_alerting} alerting" tone={o.watches_alerting ? 'bad' : ''} />
    <Stat label="SSH" value={o.ssh_hosts} hint="{o.ssh_connections} connected" />
    <Stat label="Deliveries" value={o.deliveries_failed} hint="failed · {o.deliveries_pending} pending" tone={o.deliveries_failed ? 'bad' : 'ok'} />
    <Stat label="Subscriptions" value={o.subscriptions} hint="{o.schedules} scheduled" />
    <Stat label="GitHub App" value={o.github_app ?? '—'} hint={o.github_app ? 'configured' : 'not set up'} tone={o.github_app ? 'ok' : 'warn'} />
  </div>

  <div class="cols">
    <Panel title="Spend, 30 days">
      <div class="chart">
        {#each o.daily as d (d.day)}
          <div class="bar" title="{d.day}: {usd(d.cost_usd)} · {d.turns} turns">
            <div class="fill" style="height: {Math.max(2, (d.cost_usd / max) * 100)}%"></div>
          </div>
        {:else}
          <p class="muted pad">No activity yet.</p>
        {/each}
      </div>
      <div class="row legend small muted">
        <span>7d: {usd(o.week.cost_usd)} · {o.week.turns} turns</span>
        <span>30d: {usd(o.month.cost_usd)} · {o.month.turns} turns</span>
      </div>
    </Panel>

    <Panel title="Live">
      <Live />
    </Panel>
  </div>
</Loader>

<style>
  .grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(11rem, 1fr));
    gap: .7rem;
    margin-bottom: 1.2rem;
  }
  .cols { display: grid; grid-template-columns: 1fr 1fr; gap: 1rem; }
  @media (max-width: 1100px) { .cols { grid-template-columns: 1fr; } }
  .chart { display: flex; align-items: flex-end; gap: 2px; height: 9rem; padding: 1rem; }
  .bar { flex: 1; height: 100%; display: flex; align-items: flex-end; }
  .fill { width: 100%; background: var(--accent); border-radius: 2px 2px 0 0; opacity: .75; }
  .bar:hover .fill { opacity: 1; }
  .legend { padding: 0 1rem 1rem; gap: 1.2rem; }
  .pad { padding: 1rem; }
</style>
