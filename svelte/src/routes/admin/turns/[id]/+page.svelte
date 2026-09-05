<script>
  import { page } from '$app/state';
  import { admin } from '$lib/api.js';
  import { resource } from '$lib/resource.svelte.js';
  import { money, usd, when } from '$lib/format.js';
  import Panel from '$lib/components/Panel.svelte';
  import Loader from '$lib/components/Loader.svelte';
  import Badge from '$lib/components/Badge.svelte';

  const id = page.params.id;
  const detail = resource(() => admin.get(`/turns/${id}`));
</script>

<svelte:head><title>unsafie — turn</title></svelte:head>
<h1>Turn <span class="mono small">{id.slice(0, 8)}</span></h1>

<Loader state={detail}>
  {@const t = detail.data.turn}
  <div class="stack">
    <Panel title="Details">
      <div class="pad row wide">
        <span><span class="muted">status</span> <Badge tone={t.status === 'failed' ? 'bad' : 'ok'}>{t.status}</Badge></span>
        <span><span class="muted">chat</span> <a href="/admin/chats/{t.bot_id}/{t.chat_id}" class="mono">{t.chat_id}</a></span>
        <span><span class="muted">user</span> <a href="/admin/users/{t.user_id}" class="mono">{t.user_id}</a></span>
        <span><span class="muted">steps</span> {t.num_turns}</span>
        <span><span class="muted">cost</span> {usd(t.cost_usd)}</span>
        <span><span class="muted">charged</span> {money(t.charge)}</span>
        <span><span class="muted">key</span> {t.credential_id ?? '—'}</span>
        <span><span class="muted">session</span> <span class="mono small">{t.session_id ?? '—'}</span></span>
        <span><span class="muted">started</span> {when(t.created_at)}</span>
        <span><span class="muted">finished</span> {when(t.finished_at)}</span>
      </div>
      {#if t.result}<pre class="result">{t.result}</pre>{/if}
    </Panel>

    {#if detail.data.parent || detail.data.children.length}
      <Panel title="Conversation tree">
        <ul class="tree">
          {#if detail.data.parent}
            <li><span class="muted">parent</span> <a href="/admin/turns/{detail.data.parent.id}" class="mono">{detail.data.parent.id.slice(0, 8)}</a> · {detail.data.parent.status}</li>
          {/if}
          {#each detail.data.children as c (c.id)}
            <li><span class="muted">child</span> <a href="/admin/turns/{c.id}" class="mono">{c.id.slice(0, 8)}</a> · {c.status}{c.forked ? ' ⑂ forked' : ''}</li>
          {/each}
        </ul>
      </Panel>
    {/if}

    <Panel title="Responses">
      {#if detail.data.responses.length}
        <ul class="log">
          {#each detail.data.responses as r (r.id)}
            <li>
              <div class="muted small row">
                <span>{r.kind}</span>
                <span class="mono">ids {r.message_ids.join(', ')}</span>
                <span>{when(r.created_at)}</span>
              </div>
              <div class="body">{r.content}</div>
            </li>
          {/each}
        </ul>
      {:else}
        <p class="muted pad">Nothing was sent.</p>
      {/if}
    </Panel>
  </div>
</Loader>

<style>
  .pad { padding: 1rem; }
  .wide { gap: 1.3rem; }
  .result { margin: 0 1rem 1rem; }
  .tree { list-style: none; margin: 0; padding: .6rem 1rem; display: flex; flex-direction: column; gap: .3rem; }
  .log { list-style: none; margin: 0; padding: 0; }
  .log li { padding: .6rem 1rem; border-bottom: 1px solid var(--border); }
  .log li:last-child { border-bottom: 0; }
  .body { white-space: pre-wrap; word-break: break-word; margin-top: .2rem; }
</style>
