<script>
  import { page } from '$app/state';
  import { goto } from '$app/navigation';
  import { api } from '$lib/api.js';

  let { children } = $props();

  const NAV = [
    ['/admin', 'Overview'],
    ['/admin/bots', 'Bots'],
    ['/admin/credentials', 'Keys'],
    ['/admin/config', 'Pricing'],
    ['/admin/users', 'Users'],
    ['/admin/chats', 'Chats'],
    ['/admin/turns', 'Turns'],
    ['/admin/github', 'GitHub'],
    ['/admin/subscriptions', 'Subscriptions'],
    ['/admin/deliveries', 'Deliveries'],
    ['/admin/schedule', 'Schedule'],
    ['/admin/watches', 'Watches'],
    ['/admin/ssh', 'SSH'],
    ['/admin/shares', 'Shares'],
    ['/admin/stats', 'Stats']
  ];

  const active = (href) =>
    href === '/admin' ? page.url.pathname === '/admin' : page.url.pathname.startsWith(href);

  async function logout() {
    await api.post('/api/logout');
    await goto('/login');
  }
</script>

<div class="shell">
  <nav>
    <div class="brand">unsafie</div>
    <ul>
      {#each NAV as [href, label] (href)}
        <li><a {href} class:on={active(href)}>{label}</a></li>
      {/each}
    </ul>
    <button class="out" onclick={logout}>Sign out</button>
  </nav>
  <main>{@render children?.()}</main>
</div>

<style>
  .shell { display: flex; min-height: 100vh; }
  nav {
    flex: 0 0 12rem;
    background: var(--panel);
    border-right: 1px solid var(--border);
    padding: 1rem .7rem;
    display: flex;
    flex-direction: column;
    gap: .6rem;
    position: sticky;
    top: 0;
    height: 100vh;
  }
  .brand { font-weight: 700; padding: 0 .5rem .4rem; letter-spacing: .02em; }
  ul { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 1px; flex: 1; overflow-y: auto; }
  a { display: block; padding: .32rem .5rem; border-radius: 6px; color: var(--text); font-size: .92rem; }
  a:hover { background: color-mix(in srgb, var(--accent) 10%, transparent); text-decoration: none; }
  a.on { background: color-mix(in srgb, var(--accent) 15%, transparent); color: var(--accent); font-weight: 550; }
  .out { font-size: .85rem; }
  main { flex: 1; padding: 1.3rem 1.6rem 4rem; max-width: 1400px; }
  @media (max-width: 760px) {
    .shell { flex-direction: column; }
    nav { position: static; height: auto; flex: none; border-right: 0; border-bottom: 1px solid var(--border); }
    ul { flex-direction: row; flex-wrap: wrap; }
    main { padding: 1rem; }
  }
</style>
