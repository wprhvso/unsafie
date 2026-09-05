<script>
  import { admin } from '$lib/api.js';
  import { resource } from '$lib/resource.svelte.js';
  import { when } from '$lib/format.js';
  import Panel from '$lib/components/Panel.svelte';
  import Loader from '$lib/components/Loader.svelte';
  import Pager from '$lib/components/Pager.svelte';
  import Confirm from '$lib/components/Confirm.svelte';

  let offset = $state(0);
  const subs = resource(() => admin.get('/subscriptions', { offset, limit: 50 }));
  const move = (n) => { offset = n; subs.reload(); };
</script>

<svelte:head><title>unsafie — subscriptions</title></svelte:head>
<h1>Subscriptions</h1>

<Panel>
  <Loader state={subs} empty="No subscriptions.">
    <table>
      <thead><tr><th>id</th><th>repository</th><th>kind</th><th>filters</th><th>chat</th><th>user</th><th>added</th><th></th></tr></thead>
      <tbody>
        {#each subs.data.items as s (s.id)}
          <tr>
            <td class="mono">{s.id}</td>
            <td>{s.repo}</td>
            <td>{s.kind}</td>
            <td class="mono small muted">
              {Object.entries(s.filters).map(([k, v]) => `${k}=${v}`).join(' ') || '—'}
            </td>
            <td class="mono"><a href="/admin/chats/{s.bot_id}/{s.chat_id}">{s.chat_id}</a></td>
            <td class="mono"><a href="/admin/users/{s.user_id}">{s.user_id}</a></td>
            <td class="muted small">{when(s.created_at)}</td>
            <td>
              <Confirm label="Delete" question="Delete subscription {s.id}?"
                onconfirm={async () => { await admin.del(`/subscriptions/${s.id}`); await subs.reload(); }} />
            </td>
          </tr>
        {/each}
      </tbody>
    </table>
    <Pager total={subs.data.total} {offset} limit={subs.data.limit} onmove={move} />
  </Loader>
</Panel>
