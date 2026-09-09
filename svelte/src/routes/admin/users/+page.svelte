<script>
  import { admin } from '$lib/api.js';
  import { resource } from '$lib/resource.svelte.js';
  import Panel from '$lib/components/Panel.svelte';
  import Loader from '$lib/components/Loader.svelte';
  import Pager from '$lib/components/Pager.svelte';

  let offset = $state(0);
  const users = resource(() => admin.get('/users', { offset, limit: 50 }));
  const move = (n) => { offset = n; users.reload(); };
</script>

<svelte:head><title>unsafie — users</title></svelte:head>
<h1>Users</h1>

<Panel>
  <Loader state={users} empty="No users yet.">
    <table>
      <thead><tr><th>id</th><th>locale</th><th>tz</th><th>effort</th><th>github</th><th>ssh</th></tr></thead>
      <tbody>
        {#each users.data.items as u (u.id)}
          <tr>
            <td class="mono"><a href="/admin/users/{u.id}">{u.id}</a></td>
            <td>{u.locale ?? '—'}</td>
            <td>{u.timezone ?? '—'}</td>
                        <td>{u.effort ?? '—'}</td>
            <td>{u.github_logins.join(', ') || '—'}</td>
            <td>{u.has_ssh_key ? 'yes' : '—'}</td>
          </tr>
        {/each}
      </tbody>
    </table>
    <Pager total={users.data.total} {offset} limit={users.data.limit} onmove={move} />
  </Loader>
</Panel>
