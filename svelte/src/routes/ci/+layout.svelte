<script>
  import { onMount } from 'svelte';
  import { page } from '$app/state';
  import { goto } from '$app/navigation';
  import { api } from '$lib/api.js';

  let { children } = $props();

  let user = $state(null);
  let loading = $state(true);

  onMount(async () => {
    try {
      const me = await api.get('/api/ci/auth/me');
      if (!me?.authenticated || !me?.whitelisted) {
        if (me?.login && !me?.whitelisted) {
          await goto(`/access-denied?login=${me.login}&avatar=${me.avatar_url || ''}`);
          return;
        }
      }
      user = me;
    } catch {
    } finally {
      loading = false;
    }
  });

  async function logout() {
    await api.post('/api/ci/auth/logout');
    user = null;
    await goto('/api/ci/auth/github');
  }

  const active = (href) =>
    href === '/ci' ? page.url.pathname === '/ci' : page.url.pathname.startsWith(href);
</script>

<div class="ci-shell">
  <header class="ci-header">
    <div class="brand">
      <a href="/ci"><strong>unsafie</strong> <span class="badge">CI/CD</span></a>
    </div>

    <nav class="ci-nav">
      <a href="/ci" class:on={active('/ci') && page.url.pathname === '/ci'}>Runs</a>
      <a href="/ci/secrets" class:on={active('/ci/secrets')}>Secrets</a>
      <a href="/ci/tokens" class:on={active('/ci/tokens')}>API Tokens</a>
      <a href="/ci/docs" class:on={active('/ci/docs')}>Docs</a>
    </nav>

    <div class="user-meta">
      {#if user?.authenticated}
        {#if user.avatar_url}
          <img src={user.avatar_url} alt={user.login} class="user-avatar" />
        {/if}
        <span class="username">@{user.login}</span>
        <button class="btn-out" onclick={logout}>Sign out</button>
      {:else}
        <a href="/api/ci/auth/github" class="btn-login">Sign in with GitHub</a>
      {/if}
    </div>
  </header>

  <main class="ci-main">
    {@render children?.()}
  </main>
</div>

<style>
  .ci-shell { min-height: 100vh; background: var(--bg, #0b0f17); color: var(--text, #f8fafc); }
  .ci-header { display: flex; align-items: center; justify-content: space-between; padding: 0.8rem 1.6rem; border-bottom: 1px solid var(--border, #1e293b); background: var(--panel, #111827); position: sticky; top: 0; z-index: 50; }
  .brand a { font-size: 1.15rem; font-weight: 700; color: inherit; text-decoration: none; display: flex; align-items: center; gap: 0.5rem; }
  .badge { font-size: 0.72rem; padding: 0.15rem 0.45rem; border-radius: 4px; background: #3b82f6; color: #fff; font-weight: 700; }
  .ci-nav { display: flex; gap: 1rem; }
  .ci-nav a { color: var(--muted, #94a3b8); text-decoration: none; font-size: 0.9rem; font-weight: 550; padding: 0.35rem 0.6rem; border-radius: 6px; }
  .ci-nav a:hover { color: var(--text, #f8fafc); background: rgba(255,255,255,0.05); }
  .ci-nav a.on { color: #38bdf8; background: rgba(56,189,248,0.1); }
  .user-meta { display: flex; align-items: center; gap: 0.7rem; font-size: 0.88rem; }
  .user-avatar { width: 28px; height: 28px; border-radius: 50%; border: 1px solid var(--border, #334155); }
  .username { color: var(--muted, #94a3b8); font-weight: 600; }
  .btn-out { background: transparent; border: 1px solid var(--border, #334155); color: #94a3b8; border-radius: 6px; padding: 0.25rem 0.6rem; font-size: 0.8rem; cursor: pointer; }
  .btn-out:hover { color: #f87171; border-color: #f87171; }
  .btn-login { background: #3b82f6; color: #fff; text-decoration: none; padding: 0.4rem 0.8rem; border-radius: 6px; font-weight: 600; font-size: 0.85rem; }
  .ci-main { max-width: 1300px; margin: 0 auto; padding: 1.8rem 1.5rem 4rem; }
  @media (max-width: 768px) {
    .ci-header { flex-direction: column; gap: 0.8rem; align-items: stretch; }
    .ci-nav { justify-content: center; }
  }
</style>
