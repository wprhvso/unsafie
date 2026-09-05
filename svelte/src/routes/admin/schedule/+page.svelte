<script>
  import { onMount } from 'svelte';
  import { admin } from '$lib/api.js';
  import { resource } from '$lib/resource.svelte.js';
  import { refreshOn } from '$lib/events.js';
  import { when } from '$lib/format.js';
  import Panel from '$lib/components/Panel.svelte';
  import Loader from '$lib/components/Loader.svelte';
  import Pager from '$lib/components/Pager.svelte';
  import Badge from '$lib/components/Badge.svelte';
  import Confirm from '$lib/components/Confirm.svelte';

  let offset = $state(0);
  const tasks = resource(() => admin.get('/schedule', { offset, limit: 50 }));
  const move = (n) => { offset = n; tasks.reload(); };
  onMount(() => refreshOn(['task.*'], () => tasks.reload(), 2000));

  const repeat = (t) => (t.cron ? `cron ${t.cron}` : t.interval_sec ? `every ${t.interval_sec}s` : 'once');
</script>

<svelte:head><title>unsafie — schedule</title></svelte:head>
<h1>Schedule</h1>

<Panel>
  <Loader state={tasks} empty="Nothing scheduled.">
    <table>
      <thead><tr><th>id</th><th>kind</th><th>text</th><th>repeat</th><th>next</th><th>runs</th><th>chat</th><th>state</th><th></th></tr></thead>
      <tbody>
        {#each tasks.data.items as t (t.id)}
          <tr>
            <td class="mono">{t.id}</td>
            <td>{t.kind}</td>
            <td class="text">{t.text}</td>
            <td class="mono small">{repeat(t)}</td>
            <td class="muted small nowrap">{when(t.next_run_at)}</td>
            <td>{t.runs}</td>
            <td class="mono"><a href="/admin/chats/{t.bot_id}/{t.chat_id}">{t.chat_id}</a></td>
            <td><Badge tone={t.enabled ? 'ok' : 'warn'}>{t.enabled ? 'on' : 'paused'}</Badge></td>
            <td class="row nowrap">
              <button onclick={async () => { await admin.post(`/schedule/${t.id}/pause?resume=${!t.enabled}`); await tasks.reload(); }}>
                {t.enabled ? 'Pause' : 'Resume'}
              </button>
              <Confirm label="Delete" question="Delete task {t.id}?"
                onconfirm={async () => { await admin.del(`/schedule/${t.id}`); await tasks.reload(); }} />
            </td>
          </tr>
        {/each}
      </tbody>
    </table>
    <Pager total={tasks.data.total} {offset} limit={tasks.data.limit} onmove={move} />
  </Loader>
</Panel>

<style>.text { max-width: 24rem; }</style>
