<script>
  import { goto } from '$app/navigation';
  import { api, ApiError } from '$lib/api.js';

  let token = $state('');
  let busy = $state(false);
  let error = $state('');

  async function submit() {
    if (!token.trim()) return;
    busy = true;
    error = '';
    try {
      await api.post('/api/login', { token: token.trim() });
      await goto('/admin');
    } catch (e) {
      error = e instanceof ApiError && e.status === 401 ? 'Wrong token.' : String(e.message ?? e);
      token = '';
    } finally {
      busy = false;
    }
  }
</script>

<svelte:head><title>unsafie — sign in</title></svelte:head>

<main>
  <h1>unsafie</h1>
  <p class="muted small">Paste the admin token to continue.</p>
  <div class="row">
    <input
      class="grow"
      type="password"
      autocomplete="current-password"
      placeholder="admin token"
      bind:value={token}
      onkeydown={(e) => e.key === 'Enter' && submit()}
      disabled={busy}
    />
    <button onclick={submit} disabled={busy || !token.trim()}>{busy ? '…' : 'Enter'}</button>
  </div>
  {#if error}<p class="err small">{error}</p>{/if}
</main>

<style>
  main {
    max-width: 22rem;
    margin: 22vh auto 0;
    padding: 1.4rem;
    background: var(--panel);
    border: 1px solid var(--border);
    border-radius: var(--radius);
  }
  h1 { margin-bottom: .2rem; }
  .err { color: var(--bad); margin: .6rem 0 0; }
  .row { margin-top: .9rem; }
</style>
