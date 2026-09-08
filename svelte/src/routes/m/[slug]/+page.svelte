<script>
  import { onMount, onDestroy } from 'svelte';
  import { page } from '$app/state';

  const CODES = {
    1006: 'the connection dropped before the handshake finished',
    4401: 'the machine token was refused',
    4404: 'this link has expired',
    4408: 'the machine never dialled back',
    4409: 'the machine refused the tunnel'
  };

  const NO_DESKTOP =
    'The desktop never opened. A machine only has one once browser.start() has run — ' +
    'start the browser, then ask for a fresh link.';

  let state = $state('connecting');
  let note = $state('');
  let kind = $state('vnc');
  let machine = $state('');
  let screen;
  let terminal;
  let cleanup = null;
  let opened = false;

  const slug = page.params.slug;

  function socketUrl() {
    const scheme = location.protocol === 'https:' ? 'wss' : 'ws';
    return `${scheme}://${location.host}/api/m/${slug}/stream`;
  }

  function closed(event) {
    state = 'closed';
    if (event?.reason) note = event.reason;
    else if (CODES[event?.code]) note = CODES[event.code];
    else if (!opened) note = NO_DESKTOP;
  }

  async function boot() {
    let info;
    try {
      const answer = await fetch(`/api/m/${slug}`);
      if (!answer.ok) {
        state = answer.status === 404 ? 'expired' : 'failed';
        return;
      }
      info = await answer.json();
    } catch {
      state = 'failed';
      return;
    }
    kind = info.kind;
    machine = info.machine;
    if (kind === 'term') await startTerminal();
    else await startDesktop();
  }

  async function startDesktop() {
    const { default: RFB } = await import('@novnc/novnc');
    // Hand noVNC a socket we made ourselves: it hides the close code, and the code is the
    // only place the server can say why nothing appeared.
    const socket = new WebSocket(socketUrl(), ['binary']);
    socket.binaryType = 'arraybuffer';
    socket.addEventListener('close', closed);
    const client = new RFB(screen, socket);
    client.scaleViewport = true;
    client.resizeSession = true;
    client.addEventListener('connect', () => {
      opened = true;
      state = 'live';
    });
    client.addEventListener('disconnect', () => {
      if (state !== 'closed') closed(null);
    });
    cleanup = () => {
      socket.removeEventListener('close', closed);
      client.disconnect();
    };
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
      opened = true;
      state = 'live';
      resize();
    };
    socket.onclose = closed;
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

<svelte:head><title>{kind === 'term' ? 'terminal' : 'desktop'} · {machine || slug}</title></svelte:head>

<div class="frame">
  <header>
    <span class="what">{kind === 'term' ? 'terminal' : 'live desktop'}</span>
    <span class="machine">{machine}</span>
    <span class="state {state}">{state}</span>
  </header>
  {#if state === 'expired'}
    <p class="note">This link has expired. Ask for a new one.</p>
  {:else if state === 'failed'}
    <p class="note">The machine is not answering.</p>
  {:else if note}
    <p class="note">{note}</p>
  {/if}
  <div class="screen" bind:this={screen} hidden={kind === 'term'}></div>
  <div class="terminal" bind:this={terminal} hidden={kind !== 'term'}></div>
</div>

<style>
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
  .state.closed,
  .state.failed,
  .state.expired {
    color: #f85149;
  }
  .note {
    padding: 1rem;
    margin: 0;
    color: #8b949e;
  }
  .screen,
  .terminal {
    flex: 1;
    min-height: 0;
  }
  .terminal {
    padding: 0.4rem;
  }
</style>
