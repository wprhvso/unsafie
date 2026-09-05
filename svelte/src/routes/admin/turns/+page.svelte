<script>
  import { onMount } from 'svelte';
  import { admin } from '$lib/api.js';
  import { resource } from '$lib/resource.svelte.js';
  import { refreshOn } from '$lib/events.js';
  import { money, usd, when, short } from '$lib/format.js';
  import Panel from '$lib/components/Panel.svelte';
  import Loader from '$lib/components/Loader.svelte';
  import Pager from '$lib/components/Pager.svelte';
  import Badge from '$lib/components/Badge.svelte';

  let offset = $state(0);
  let status = $state('');
  const turns = resource(() => admin.get('/turns', { offset, limit: 50, ...(status ? { status } : {}) }));
  const move = (n) => { offset = n; turns.reload(); };
  onMount(() => refreshOn(['turn.*'], () => turns.reload(), 2000));

  const tone = (s) => (s === 'failed' ? 'bad' : s === 'running' ? 'warn' : 'ok');
</script>

<svelte:head><title>unsafie — turns</title></svelte:head>
<h1>Turns</h1>

<Panel>
  {#snippet actions()}
    <select bind:value={status} onchange={() => move(0)}>
      <option value="">all</option>
      <option value="running">running</option>
      <option value="done">done</option>
      <option value="failed">failed</option>
    </select>
  {/snippet}

  <Loader state={turns} empty="No turns.">
    <table>
      <thead>
        <tr><th>id</th><th>chat</th><th>user</th><th>status</th><th>steps</th><th>cost</th><th>charge</th><th>result</th><th>when</th></tr>
      </thead>
      <tbody>
        {#each turns.data.items as t (t.id)}
          <tr>
            <td class="mono"><a href="/admin/turns/{t.id}">{t.id.slice(0, 8)}</a>{t.forked ? ' ⑂' : ''}</td>
            <td class="mono"><a href="/admin/chats/{t.bot_id}/{t.chat_id}">{t.chat_id}</a></td>
            <td class="mono">{t.user_id}</td>
            <td><Badge tone={tone(t.status)}>{t.status}</Badge></td>
            <td>{t.num_turns}</td>
            <td>{usd(t.cost_usd)}</td>
            <td>{money(t.charge)}</td>
            <td class="small muted">{short(t.result, 60)}</td>
            <td class="muted small nowrap">{when(t.created_at)}</td>
          </tr>
        {/each}
      </tbody>
    </table>
    <Pager total={turns.data.total} {offset} limit={turns.data.limit} onmove={move} />
  </Loader>
</Panel>
