<script>
  import { admin } from '$lib/api.js';
  import { resource } from '$lib/resource.svelte.js';
  import { when, duration } from '$lib/format.js';
  import Panel from '$lib/components/Panel.svelte';
  import Loader from '$lib/components/Loader.svelte';
  import Pager from '$lib/components/Pager.svelte';
  import Badge from '$lib/components/Badge.svelte';

  let offset = $state(0);
  const hosts = resource(() => admin.get('/ssh/hosts', { offset, limit: 50 }));
  const conns = resource(() => admin.get('/ssh/connections'));
  const move = (n) => { offset = n; hosts.reload(); };

  async function disconnect(id) {
    await admin.post(`/ssh/hosts/${id}/disconnect`);
    await Promise.all([hosts.reload(), conns.reload()]);
  }
</script>

<svelte:head><title>unsafie — ssh</title></svelte:head>
<h1>SSH</h1>

<div class="stack">
  <Panel title="Hosts">
    <Loader state={hosts} empty="No hosts.">
      <table>
        <thead><tr><th>id</th><th>user</th><th>alias</th><th>target</th><th>fingerprint</th><th>state</th><th>last used</th><th></th></tr></thead>
        <tbody>
          {#each hosts.data.items as h (h.id)}
            <tr>
              <td class="mono">{h.id}</td>
              <td class="mono"><a href="/admin/users/{h.user_id}">{h.user_id}</a></td>
              <td>{h.alias}</td>
              <td class="mono small">{h.username}@{h.host}{h.port === 22 ? '' : `:${h.port}`}</td>
              <td class="mono small muted">{h.fingerprint ?? 'not pinned'}</td>
              <td><Badge tone={h.connected ? 'ok' : ''}>{h.connected ? 'connected' : 'idle'}</Badge></td>
              <td class="muted small">{when(h.last_used_at)}</td>
              <td>{#if h.connected}<button onclick={() => disconnect(h.id)}>Disconnect</button>{/if}</td>
            </tr>
          {/each}
        </tbody>
      </table>
      <Pager total={hosts.data.total} {offset} limit={hosts.data.limit} onmove={move} />
    </Loader>
  </Panel>

  <Panel title="Live connections">
    {#snippet actions()}<button onclick={() => conns.reload()}>Refresh</button>{/snippet}
    <Loader state={conns} empty="Nothing is connected.">
      <table>
        <thead><tr><th>user</th><th>host id</th><th>idle</th><th>alive</th></tr></thead>
        <tbody>
          {#each conns.data as c (`${c.user_id}-${c.host_id}`)}
            <tr>
              <td class="mono">{c.user_id}</td>
              <td class="mono">{c.host_id}</td>
              <td>{duration(c.idle_sec)}</td>
              <td>{c.alive ? 'yes' : 'no'}</td>
            </tr>
          {/each}
        </tbody>
      </table>
    </Loader>
  </Panel>
</div>
