<script>
  import { admin } from '$lib/api.js';
  import { resource } from '$lib/resource.svelte.js';
  import { when } from '$lib/format.js';
  import Panel from '$lib/components/Panel.svelte';
  import Loader from '$lib/components/Loader.svelte';
  import Badge from '$lib/components/Badge.svelte';
  import Confirm from '$lib/components/Confirm.svelte';

  const app = resource(() => admin.get('/github/app'));
  const installations = resource(() => admin.get('/github/installations'));
  const accounts = resource(() => admin.get('/github/accounts'));
  const repos = resource(() => admin.get('/github/repos', { limit: 200 }));
  const worktrees = resource(() => admin.get('/github/worktrees', { limit: 100 }));

  const reloadAll = () =>
    Promise.all([app.reload(), installations.reload(), accounts.reload(), repos.reload()]);
</script>

<svelte:head><title>unsafie — github</title></svelte:head>
<h1>GitHub</h1>

<div class="stack">
  <Loader state={app}>
    {@const a = app.data}
    <Panel title="App">
      {#if a.configured}
        <div class="pad stack">
          <div class="row wide">
            <span><span class="muted">name</span> <b>{a.app.name}</b></span>
            <span><span class="muted">slug</span> <span class="mono">{a.app.slug}</span></span>
            <span><span class="muted">app id</span> <span class="mono">{a.app.app_id}</span></span>
            <span><span class="muted">created</span> {when(a.app.created_at)}</span>
          </div>
          <div class="row wide small">
            <a href={a.app.html_url} target="_blank" rel="noreferrer">App page</a>
            <a href={a.install_url} target="_blank" rel="noreferrer">Install on repositories</a>
            <span class="muted mono">{a.webhook_url}</span>
          </div>
          <Confirm
            label="Forget app credentials"
            question="This deletes the private key and webhook secret. Webhooks will stop working until a new app is created. Sure?"
            onconfirm={async () => { await admin.del('/github/app'); await reloadAll(); }}
          />
        </div>
      {:else}
        <div class="pad stack">
          <p class="muted">
            No GitHub App yet. Creating one takes a single click: GitHub will ask you to confirm a
            manifest, then hand the credentials back automatically. Users work through their own
            personal access tokens; the App only carries what a token cannot — webhook delivery
            and the Checks API.
          </p>
          <div class="row">
            <a class="button" href={a.create_url}>Create the GitHub App</a>
            <button onclick={reloadAll}>I have created it</button>
          </div>
          <details>
            <summary class="muted small">What it will ask for</summary>
            <div class="perms small mono">
              {#each Object.entries(a.permissions) as [name, level] (name)}
                <span>{name}: {level}</span>
              {/each}
            </div>
            <p class="muted small">webhook → {a.webhook_url}</p>
          </details>
        </div>
      {/if}
    </Panel>
  </Loader>

  <Panel title="Installations">
    <Loader state={installations} empty="The app is not installed anywhere yet.">
      <table>
        <thead><tr><th>id</th><th>account</th><th>type</th><th>scope</th><th>state</th><th>added</th><th></th></tr></thead>
        <tbody>
          {#each installations.data as i (i.id)}
            <tr>
              <td class="mono">{i.id}</td>
              <td>{i.account_login}</td>
              <td class="muted">{i.account_type}</td>
              <td>{i.repository_selection}</td>
              <td><Badge tone={i.suspended ? 'bad' : 'ok'}>{i.suspended ? 'suspended' : 'active'}</Badge></td>
              <td class="muted small">{when(i.created_at)}</td>
              <td>
                <Confirm
                  label="Forget"
                  question="Remove installation {i.id} and its repositories from the database?"
                  onconfirm={async () => { await admin.del(`/github/installations/${i.id}`); await reloadAll(); }}
                />
              </td>
            </tr>
          {/each}
        </tbody>
      </table>
    </Loader>
  </Panel>

  <Panel title="Connected accounts">
    <Loader state={accounts} empty="Nobody has connected a GitHub account.">
      <table>
        <thead><tr><th>id</th><th>user</th><th>login</th><th>token</th><th>scopes</th><th>connected</th></tr></thead>
        <tbody>
          {#each accounts.data.items as a (a.id)}
            <tr>
              <td class="mono">{a.id}</td>
              <td class="mono"><a href="/admin/users/{a.user_id}">{a.user_id}</a></td>
              <td>{a.login}</td>
              <td><Badge tone={a.has_token ? 'ok' : 'warn'}>{a.has_token ? 'yes' : 'none'}</Badge></td>
              <td class="muted small mono">{a.scopes ?? 'fine-grained'}</td>
              <td class="muted small">{when(a.created_at)}</td>
            </tr>
          {/each}
        </tbody>
      </table>
    </Loader>
  </Panel>

  <Panel title="Repositories">
    <Loader state={repos} empty="No repositories.">
      <table>
        <thead><tr><th>id</th><th>repository</th><th>branch</th><th>visibility</th><th>installation</th></tr></thead>
        <tbody>
          {#each repos.data.items as r (r.id)}
            <tr>
              <td class="mono">{r.id}</td>
              <td><a href="https://github.com/{r.owner}/{r.name}" target="_blank" rel="noreferrer">{r.owner}/{r.name}</a></td>
              <td class="mono">{r.default_branch}</td>
              <td class="muted">{r.private ? 'private' : 'public'}</td>
              <td class="mono">{r.installation_id ?? '—'}</td>
            </tr>
          {/each}
        </tbody>
      </table>
    </Loader>
  </Panel>

  <Panel title="Worktrees">
    <Loader state={worktrees} empty="No open worktrees.">
      <table>
        <thead><tr><th>id</th><th>repository</th><th>branch</th><th>head</th><th>uncommitted</th><th>stash</th><th>updated</th></tr></thead>
        <tbody>
          {#each worktrees.data.items as w (w.id)}
            <tr>
              <td class="mono">{w.id}</td>
              <td>{w.repo}</td>
              <td class="mono">{w.branch}</td>
              <td class="mono muted">{w.base_commit_sha.slice(0, 7)}</td>
              <td class:warn={w.changes > 0}>{w.changes}</td>
              <td>{w.stashed}</td>
              <td class="muted small">{when(w.updated_at)}</td>
            </tr>
          {/each}
        </tbody>
      </table>
    </Loader>
  </Panel>
</div>

<style>
  .pad { padding: 1rem; }
  .wide { gap: 1.3rem; }
  .warn { color: var(--warn); }
  .perms { display: flex; flex-wrap: wrap; gap: .3rem .9rem; margin: .5rem 0; }
  .button { display: inline-block; text-decoration: none; }
</style>
