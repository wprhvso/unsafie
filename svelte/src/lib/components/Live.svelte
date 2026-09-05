<script>
  import { onMount } from 'svelte';
  import { subscribe } from '$lib/events.js';

  let { kinds = ['turn.*', 'webhook.*', 'watch.*', 'task.*', 'credential.*', 'bot.*'], limit = 40 } = $props();
  let items = $state([]);
  let connected = $state(false);

  const TONE = {
    'turn.finished': (e) => (e.data.status === 'failed' ? 'bad' : 'ok'),
    'watch.fired': () => 'bad',
    'watch.recovered': () => 'ok',
    'credential.failed': () => 'warn',
    'bot.crashed': () => 'bad'
  };

  onMount(() =>
    subscribe({
      kinds,
      onEvent: (e) => {
        connected = true;
        items = [e, ...items].slice(0, limit);
      },
      onGap: () => (items = [])
    })
  );

  function line(e) {
    const d = e.data ?? {};
    switch (e.kind) {
      case 'turn.started': return `chat ${d.chat_id} · user ${d.user_id}`;
      case 'turn.finished': return `chat ${d.chat_id} · ${d.status}${d.cost_usd ? ` · $${d.cost_usd.toFixed(4)}` : ''}`;
      case 'webhook.received': return `${d.event}${d.action ? `.${d.action}` : ''} · ${d.repo ?? '?'} · ${d.sender ?? ''}`;
      case 'webhook.processed': return `${d.delivery_id?.slice(0, 8)} · sent ${d.notified}${d.error ? ` · ${d.error}` : ''}`;
      case 'watch.fired':
      case 'watch.recovered': return `${d.name} on ${d.host}${d.reason ? ` · ${d.reason}` : ''}`;
      case 'task.fired': return `chat ${d.chat_id} · ${d.text ?? ''}`;
      case 'credential.failed': return `#${d.credential_id} ${d.failure}${d.disabled ? ' · disabled' : ''}`;
      case 'bot.started':
      case 'bot.stopped':
      case 'bot.crashed': return `bot ${d.bot_id}${d.username ? ` @${d.username}` : ''}${d.error ? ` · ${d.error}` : ''}`;
      default: return JSON.stringify(d);
    }
  }
</script>

<ul>
  {#each items as e (e.id)}
    <li>
      <time class="muted mono">{new Date(e.at).toLocaleTimeString()}</time>
      <span class="kind {TONE[e.kind]?.(e) ?? ''}">{e.kind}</span>
      <span class="text">{line(e)}</span>
    </li>
  {:else}
    <li class="muted idle">{connected ? 'Waiting for events…' : 'Connecting…'}</li>
  {/each}
</ul>

<style>
  ul { list-style: none; margin: 0; padding: 0; max-height: 22rem; overflow-y: auto; }
  li { display: flex; gap: .55rem; padding: .3rem 1rem; border-bottom: 1px solid var(--border); font-size: .87rem; }
  li:last-child { border-bottom: 0; }
  li.idle { padding: 1rem; }
  time { font-size: .8rem; flex: 0 0 auto; }
  .kind { flex: 0 0 auto; font-family: var(--mono); font-size: .8rem; color: var(--muted); }
  .kind.ok { color: var(--ok); }
  .kind.bad { color: var(--bad); }
  .kind.warn { color: var(--warn); }
  .text { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
</style>
