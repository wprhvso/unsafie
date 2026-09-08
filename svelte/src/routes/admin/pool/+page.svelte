<script>
  import { admin } from '$lib/api.js';
  import { resource } from '$lib/resource.svelte.js';
  import { when, duration } from '$lib/format.js';
  import Panel from '$lib/components/Panel.svelte';
  import Loader from '$lib/components/Loader.svelte';
  import Badge from '$lib/components/Badge.svelte';
  import Stat from '$lib/components/Stat.svelte';
  import Confirm from '$lib/components/Confirm.svelte';

  const capacity = resource(() => admin.get('/pool/capacity'));
  const donors = resource(() => admin.get('/pool/donors'));
  const machines = resource(() => admin.get('/pool/machines'));
  const ci = resource(() => admin.get('/pool/ci'));
  const users = resource(() => admin.get('/pool/users'));

  let token = $state('');
  let jobs = $state(20);
  let label = $state('');
  let issued = $state(null);
  let busy = $state(false);
  let problem = $state('');

  const reloadAll = () =>
    Promise.all([capacity.reload(), donors.reload(), machines.reload(), ci.reload(), users.reload()]);

  async function guard(work) {
    busy = true;
    problem = '';
    try {
      await work();
    } catch (failure) {
      problem = failure?.message ?? String(failure);
    } finally {
      busy = false;
    }
  }

  const addDonor = () =>
    guard(async () => {
      const answer = await admin.post('/pool/donors', { token, jobs: Number(jobs), label: label || null });
      issued = answer;
      token = '';
      label = '';
      await donors.reload();
    });

  const bootstrap = (login) =>
    guard(async () => {
      await admin.post(`/pool/donors/${login}/bootstrap`);
      await donors.reload();
    });

  const rotate = (login) =>
    guard(async () => {
      issued = await admin.post(`/pool/donors/${login}/rotate`);
      await donors.reload();
    });

  const toggleDonor = (donor) =>
    guard(async () => {
      await admin.post(`/pool/donors/${donor.login}/enable?on=${!donor.enabled}`);
      await donors.reload();
    });

  const dropDonor = (login) =>
    guard(async () => {
      await admin.del(`/pool/donors/${login}`);
      await donors.reload();
    });

  const recycle = (name) =>
    guard(async () => {
      await admin.post(`/pool/machines/${name}/recycle`);
      await Promise.all([machines.reload(), capacity.reload()]);
    });

  const toggleCi = (repo) =>
    guard(async () => {
      await admin.post(`/pool/ci/${repo.repo}/enable?on=${!repo.enabled}`);
      await ci.reload();
    });

  const setQuota = (user, field, value) =>
    guard(async () => {
      await admin.post(`/pool/users/${user.user_id}/quota`, { [field]: value });
      await users.reload();
    });

  const tone = (state) =>
    state === 'leased' ? 'ok' : state === 'ci' ? 'warn' : state === 'idle' ? '' : 'muted';
</script>

<svelte:head><title>unsafie — pool</title></svelte:head>
<h1>Pool</h1>

{#if problem}<p class="bad">{problem}</p>{/if}

<div class="stack">
  <Panel title="Capacity">
    {#snippet actions()}<button onclick={reloadAll} disabled={busy}>Refresh</button>{/snippet}
    <Loader state={capacity} empty="No answer.">
      <div class="stats">
        <Stat label="idle" value={capacity.data.machines.idle ?? 0} />
        <Stat label="leased" value={capacity.data.machines.leased ?? 0} />
        <Stat label="ci" value={capacity.data.machines.ci ?? 0} />
        <Stat label="alive" value={capacity.data.machines.total ?? 0} />
        <Stat label="donors" value={capacity.data.donors} />
        <Stat label="target jobs" value={capacity.data.target_jobs} />
      </div>
    </Loader>
  </Panel>

  <Panel title="Donors">
    <Loader state={donors} empty="No donors yet — the pool has no machines without them.">
      <table>
        <thead><tr><th>login</th><th>repository</th><th>jobs</th><th>state</th><th>last seen</th><th></th></tr></thead>
        <tbody>
          {#each donors.data.donors as donor (donor.id)}
            <tr>
              <td class="mono">{donor.login}{donor.label ? ` · ${donor.label}` : ''}</td>
              <td class="mono small">{donor.repo} / {donor.workflow}</td>
              <td>{donor.jobs}</td>
              <td>
                <Badge tone={donor.enabled ? (donor.state === 'ready' ? 'ok' : 'warn') : ''}>
                  {donor.enabled ? donor.state : 'disabled'}
                </Badge>
                {#if donor.last_error}<div class="small bad">{donor.last_error}</div>{/if}
              </td>
              <td class="muted small">{when(donor.reconciled_at)}</td>
              <td class="row">
                <button onclick={() => bootstrap(donor.login)} disabled={busy}>Bootstrap</button>
                <button onclick={() => rotate(donor.login)} disabled={busy}>Rotate</button>
                <button onclick={() => toggleDonor(donor)} disabled={busy}>
                  {donor.enabled ? 'Disable' : 'Enable'}
                </button>
                <Confirm label="Remove" onconfirm={() => dropDonor(donor.login)} />
              </td>
            </tr>
          {/each}
        </tbody>
      </table>
    </Loader>

    <form class="add" onsubmit={(event) => { event.preventDefault(); addDonor(); }}>
      <input bind:value={token} placeholder="github token with repo + workflow" />
      <input bind:value={jobs} type="number" min="1" max="40" />
      <input bind:value={label} placeholder="label (optional)" />
      <button type="submit" disabled={busy || !token}>Add donor</button>
    </form>
    {#if issued?.worker_token}
      <p class="small">
        Worker token (shown once): <code>{issued.worker_token}</code> — bootstrap the donor so its
        jobs get it.
      </p>
    {/if}
  </Panel>

  <Panel title="Machines">
    <Loader state={machines} empty="No machines alive.">
      <table>
        <thead><tr><th>machine</th><th>alias</th><th>state</th><th>profile</th><th>user</th><th>boot</th><th>started</th><th></th></tr></thead>
        <tbody>
          {#each machines.data.machines as machine (machine.name)}
            <tr>
              <td class="mono small">{machine.name}</td>
              <td>{machine.alias ?? '—'}</td>
              <td><Badge tone={tone(machine.state)}>{machine.state}</Badge></td>
              <td class="small">{machine.profile}</td>
              <td class="mono">
                {#if machine.user_id}<a href="/admin/users/{machine.user_id}">{machine.user_id}</a>{:else}—{/if}
              </td>
              <td class="small muted">{machine.boot_seconds ? `${Math.round(machine.boot_seconds)}s` : '—'}</td>
              <td class="small muted">{when(machine.started_at)}</td>
              <td><Confirm label="Destroy" onconfirm={() => recycle(machine.name)} /></td>
            </tr>
          {/each}
        </tbody>
      </table>
    </Loader>
  </Panel>

  <Panel title="CI on the pool">
    <Loader state={ci} empty="No repositories wired.">
      <table>
        <thead><tr><th>repository</th><th>user</th><th>label</th><th>runners</th><th>state</th><th></th></tr></thead>
        <tbody>
          {#each ci.data.repos as repo (repo.id)}
            <tr>
              <td class="mono">{repo.repo}</td>
              <td class="mono"><a href="/admin/users/{repo.user_id}">{repo.user_id}</a></td>
              <td><code>runs-on: {repo.label}</code></td>
              <td>{repo.runners}/{repo.jobs}</td>
              <td>
                <Badge tone={repo.enabled ? (repo.state === 'ready' ? 'ok' : 'warn') : ''}>
                  {repo.enabled ? repo.state : 'paused'}
                </Badge>
                {#if repo.last_error}<div class="small bad">{repo.last_error}</div>{/if}
              </td>
              <td>
                <button onclick={() => toggleCi(repo)} disabled={busy}>
                  {repo.enabled ? 'Pause' : 'Resume'}
                </button>
              </td>
            </tr>
          {/each}
        </tbody>
      </table>
    </Loader>
  </Panel>

  <Panel title="Users">
    <Loader state={users} empty="Nobody is using the pool.">
      <table>
        <thead><tr><th>user</th><th>now</th><th>machines</th><th>minutes today</th><th>commands</th><th>priority</th><th></th></tr></thead>
        <tbody>
          {#each users.data.users as user (user.user_id)}
            <tr>
              <td class="mono"><a href="/admin/users/{user.user_id}">{user.user_id}</a></td>
              <td>{user.machines_now}</td>
              <td>
                <input
                  class="tiny"
                  type="number"
                  min="0"
                  value={user.max_machines}
                  onchange={(event) => setQuota(user, 'machines', Number(event.currentTarget.value))}
                />
              </td>
              <td class="small">
                {user.minutes_today} / {user.max_minutes_day}
              </td>
              <td class="small muted">{user.commands_today}</td>
              <td>
                <input
                  class="tiny"
                  type="number"
                  value={user.priority}
                  onchange={(event) => setQuota(user, 'priority', Number(event.currentTarget.value))}
                />
              </td>
              <td>
                <button onclick={() => setQuota(user, 'blocked', !user.blocked)} disabled={busy}>
                  {user.blocked ? 'Unblock' : 'Block'}
                </button>
              </td>
            </tr>
          {/each}
        </tbody>
      </table>
    </Loader>
  </Panel>
</div>

<style>
  .stats { display: flex; flex-wrap: wrap; gap: 1.2rem; }
  .add { display: flex; gap: .5rem; margin-top: .8rem; flex-wrap: wrap; }
  .add input { flex: 1 1 12rem; }
  .add input[type='number'] { flex: 0 0 5rem; }
  .row { display: flex; gap: .3rem; flex-wrap: wrap; }
  .tiny { width: 4.5rem; }
  .bad { color: var(--bad, #c33); }
  .small { font-size: .85rem; }
</style>
