<script>
  import { onMount, onDestroy } from 'svelte';
  import { page } from '$app/state';

  let state = $state('connecting');
  let note = $state('');
  let kind = $state('term');
  let machine = $state('');
  let terminal;
  let cleanup = null;

  const slug = page.params.slug;

  function socketUrl() {
    const scheme = location.protocol === 'https:' ? 'wss' : 'ws';
    return `${scheme}://${location.host}/api/m/${slug}/stream`;
  }

  async function boot() {
    try {
      const answer = await fetch(`/api/m/${slug}`);
      if (!answer.ok) {
        state = answer.status === 404 ? 'expired' : 'failed';
        return;
      }
      const info = await answer.json();
      kind = info.kind;
      machine = info.machine;
      if (kind === 'term') {
        await startTerminal();
      } else {
        state = 'live';
      }
    } catch {
      state = 'failed';
    }
  }

  async function startTerminal() {
    const [{ Terminal }, { FitAddon }] = await Promise.all([
      import('@xterm/xterm'),
      import('@xterm/addon-fit')
    ]);
    await import('@xterm/xterm/css/xterm.css');
    const term = new Terminal({ fontSize: 13, theme: { background: '#0b0d10' } });
    const fit = new FitAddon();
    term.loadAddon(fit);
    term.open(terminal);
    fit.fit();
    const socket = new WebSocket(socketUrl());
    socket.binaryType = 'arraybuffer';
    const resize = () => {
      fit.fit();
      if (socket.readyState === 1) {
        socket.send(new TextEncoder().encode(`\u001b]resize${term.cols}x${term.rows}`));
      }
    };
    socket.onopen = () => {
      state = 'live';
      resize();
    };
    socket.onclose = () => {
      state = 'closed';
    };
    socket.onmessage = (event) => term.write(new Uint8Array(event.data));
    term.onData((data) => socket.readyState === 1 && socket.send(new TextEncoder().encode(data)));
    window.addEventListener('resize', resize);
    cleanup = () => {
      window.removeEventListener('resize', resize);
      socket.close();
      term.dispose();
    };
  }

  onMount(boot);
  onDestroy(() => cleanup && cleanup());
</script>

<svelte:head>
  <title>{kind === 'term' ? 'terminal' : 'machine'} · {machine || slug}</title>
</svelte:head>

<div class="frame">
  {#if state === 'expired'}
    <p class="note">This link has expired. Ask for a new one.</p>
  {:else if state === 'failed'}
    <p class="note">The machine is not answering.</p>
  {:else}
    <header>
      <span class="what">{kind === 'term' ? 'terminal' : 'tunnel'}</span>
      <span class="machine">{machine}</span>
      <span class="state {state}">{state}</span>
    </header>
    <div class="terminal" bind:this={terminal}></div>
  {/if}
</div>

<style>
  :global(body, html) {
    margin: 0;
    padding: 0;
    height: 100%;
    overflow: hidden;
    background: #0b0d10;
  }
  .frame {
    display: flex;
    flex-direction: column;
    height: 100dvh;
    background: #0b0d10;
    color: #d8dee9;
  }
  header {
    display: flex;
    gap: 0.75rem;
    align-items: center;
    padding: 0.5rem 0.9rem;
    font: 500 13px/1.2 ui-monospace, monospace;
    border-bottom: 1px solid #1c2128;
  }
  .machine {
    color: #8b949e;
  }
  .state {
    margin-left: auto;
    text-transform: uppercase;
    font-size: 11px;
    letter-spacing: 0.08em;
  }
  .state.live {
    color: #3fb950;
  }
  .note {
    padding: 1rem;
    margin: 0;
    color: #8b949e;
  }
  .terminal {
    flex: 1;
    min-height: 0;
    padding: 0.4rem;
  }
</style>
