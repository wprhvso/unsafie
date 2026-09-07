<script>
  import { admin } from '$lib/api.js';
  import { resource } from '$lib/resource.svelte.js';
  import { when, bytes } from '$lib/format.js';
  import Panel from '$lib/components/Panel.svelte';
  import Loader from '$lib/components/Loader.svelte';
  import Pager from '$lib/components/Pager.svelte';
  import Confirm from '$lib/components/Confirm.svelte';

  let offset = $state(0);
  const artifacts = resource(() => admin.get('/artifacts', { offset, limit: 50 }));
  const move = (n) => { offset = n; artifacts.reload(); };
</script>

<svelte:head><title>unsafie — artifacts</title></svelte:head>
<h1>Artifacts</h1>

<Panel>
  <Loader state={artifacts} empty="Nothing has been published.">
    <table>
      <thead><tr><th>slug</th><th>kind</th><th>title</th><th>link</th><th>size</th><th>turn</th><th>created</th><th></th></tr></thead>
      <tbody>
        {#each artifacts.data.items as a (a.id)}
          <tr>
            <td class="mono">{a.slug}</td>
            <td class="small muted">{a.kind}</td>
            <td class="small">{a.title ?? ''}</td>
            <td><a href={a.url} target="_blank" rel="noreferrer">open</a></td>
            <td class="small muted nowrap">{a.bytes ? bytes(a.bytes) : ''}</td>
            <td class="mono small muted">{a.turn_id ? a.turn_id.slice(0, 8) : ''}</td>
            <td class="muted small">{when(a.created_at)}</td>
            <td>
              <Confirm label="Delete" question="Revoke {a.slug}?"
                onconfirm={async () => { await admin.del(`/artifacts/${a.slug}`); await artifacts.reload(); }} />
            </td>
          </tr>
        {/each}
      </tbody>
    </table>
    <Pager total={artifacts.data.total} {offset} limit={artifacts.data.limit} onmove={move} />
  </Loader>
</Panel>
