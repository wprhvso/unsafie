<script>
  import { admin } from '$lib/api.js';
  import { resource } from '$lib/resource.svelte.js';
  import { when } from '$lib/format.js';
  import Panel from '$lib/components/Panel.svelte';
  import Loader from '$lib/components/Loader.svelte';
  import Pager from '$lib/components/Pager.svelte';
  import Confirm from '$lib/components/Confirm.svelte';

  let offset = $state(0);
  const shares = resource(() => admin.get('/shares', { offset, limit: 50 }));
  const move = (n) => { offset = n; shares.reload(); };
</script>

<svelte:head><title>unsafie — shares</title></svelte:head>
<h1>Shared answers</h1>

<Panel>
  <Loader state={shares} empty="Nothing has been shared.">
    <table>
      <thead><tr><th>slug</th><th>link</th><th>response</th><th>created</th><th></th></tr></thead>
      <tbody>
        {#each shares.data.items as s (s.id)}
          <tr>
            <td class="mono">{s.slug}</td>
            <td><a href={s.url} target="_blank" rel="noreferrer">open</a></td>
            <td class="mono small muted">{s.response_id.slice(0, 8)}</td>
            <td class="muted small">{when(s.created_at)}</td>
            <td>
              <Confirm label="Delete" question="Revoke {s.slug}?"
                onconfirm={async () => { await admin.del(`/shares/${s.slug}`); await shares.reload(); }} />
            </td>
          </tr>
        {/each}
      </tbody>
    </table>
    <Pager total={shares.data.total} {offset} limit={shares.data.limit} onmove={move} />
  </Loader>
</Panel>
