<script>
  import { page } from '$app/state';
  import { admin } from '$lib/api.js';
  import { resource } from '$lib/resource.svelte.js';
  import { when } from '$lib/format.js';
  import Panel from '$lib/components/Panel.svelte';
  import Loader from '$lib/components/Loader.svelte';

  const id = page.params.id;
  const user = resource(() => admin.get(`/users/${id}`));
  const turns = resource(() => admin.get('/turns', { user_id: id, limit: 20 }));
</script>

<svelte:head><title>unsafie — user {id}</title></svelte:head>
<h1>User {id}</h1>

<div class="stack">
  <Loader state={user}>
    {@const u = user.data}
    <Panel title="Account">
      <div class="pad stack">
        <div class="row wide">
          <span><span class="muted">locale</span> {u.locale ?? '—'}</span>
          <span><span class="muted">timezone</span> {u.timezone ?? '—'}</span>
                    <span><span class="muted">effort</span> {u.effort ?? 'default'}</span>
          <span><span class="muted">git</span> {u.git_name ? `${u.git_name} <${u.git_email}>` : '—'}</span>
          <span><span class="muted">github</span> {u.github_logins.join(', ') || '—'}</span>
          <span><span class="muted">ssh key</span> {u.has_ssh_key ? 'yes' : 'no'}</span>
        </div>
      </div>
    </Panel>
  </Loader>

  <Panel title="Recent turns">
    <Loader state={turns} empty="No turns.">
      <table>
        <thead><tr><th>id</th><th>chat</th><th>status</th><th>steps</th><th>when</th></tr></thead>
        <tbody>
          {#each turns.data.items as t (t.id)}
            <tr>
              <td class="mono"><a href="/admin/turns/{t.id}">{t.id.slice(0, 8)}</a></td>
              <td class="mono">{t.chat_id}</td>
              <td>{t.status}</td>
              <td>{t.num_turns}</td>
              <td class="muted">{when(t.created_at)}</td>
            </tr>
          {/each}
        </tbody>
      </table>
    </Loader>
  </Panel>
</div>

<style>
  .pad { padding: 1rem; }
  .wide { gap: 1.4rem; }
</style>
