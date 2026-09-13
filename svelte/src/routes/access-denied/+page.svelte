<script>
  import { page } from '$app/state';
  import { goto } from '$app/navigation';
  import { api } from '$lib/api.js';

  let login = $derived(page.url.searchParams.get('login') || 'unknown');
  let avatar = $derived(page.url.searchParams.get('avatar') || '');
  let copied = $state(false);

  function copyRequest() {
    const text = `Прошу добавить @${login} в вайтлист unsafie.com`;
    navigator.clipboard.writeText(text);
    copied = true;
    setTimeout(() => { copied = false; }, 2500);
  }

  async function logout() {
    await api.post('/api/ci/auth/logout');
    await goto('/api/ci/auth/github');
  }
</script>

<svelte:head><title>Access Restricted — unsafie.com</title></svelte:head>

<div class="wrap">
  <div class="card">
    <div class="avatar-wrap">
      {#if avatar}
        <img src={avatar} alt={login} class="avatar" />
      {:else}
        <div class="avatar placeholder">?</div>
      {/if}
      <span class="badge">🔒</span>
    </div>

    <h1>Access Restricted</h1>
    <p class="subtitle">Root Execution Environment</p>

    <div class="notice">
      Воркфлоу на <strong>unsafie.com</strong> выполняются с правами <code>root</code> прямо на хосте сервера.
      Доступ к консоли запуска, просмотру логов и управлению деплоем разрешен только для подтвержденных GitHub-аккаунтов из белого списка.
    </div>

    <div class="user-pill">
      <span>GitHub аккаунт:</span>
      <strong>@{login}</strong>
      <span class="tag bad">Не в вайтлисте</span>
    </div>

    <div class="actions">
      <button class="btn primary" onclick={copyRequest}>
        {copied ? '✓ Скопировано в буфер!' : '📋 Скопировать запрос доступа'}
      </button>

      <a href="https://t.me/unsafie" target="_blank" rel="noreferrer" class="btn outline">
        💬 Написать администратору
      </a>

      <button class="btn text" onclick={logout}>
        Войти под другим аккаунтом
      </button>
    </div>
  </div>
</div>

<style>
  .wrap { min-height: 100vh; display: flex; align-items: center; justify-content: center; padding: 1.5rem; background: var(--bg, #0b0f17); }
  .card { max-width: 520px; width: 100%; background: var(--panel, #151d2a); border: 1px solid var(--border, #243042); border-radius: 14px; padding: 2.5rem 2rem; text-align: center; box-shadow: 0 12px 40px rgba(0,0,0,0.5); }
  .avatar-wrap { position: relative; width: 84px; height: 84px; margin: 0 auto 1.2rem; }
  .avatar { width: 100%; height: 100%; border-radius: 50%; border: 2px solid var(--border, #243042); object-fit: cover; }
  .avatar.placeholder { display: flex; align-items: center; justify-content: center; font-size: 2rem; font-weight: 700; background: #1e293b; color: #94a3b8; }
  .badge { position: absolute; bottom: -2px; right: -2px; width: 28px; height: 28px; background: #ef4444; border-radius: 50%; display: flex; align-items: center; justify-content: center; font-size: 14px; border: 2px solid var(--panel, #151d2a); }
  h1 { font-size: 1.6rem; font-weight: 700; margin: 0 0 0.2rem; color: #f8fafc; }
  .subtitle { font-size: 0.9rem; text-transform: uppercase; letter-spacing: 0.08em; color: #ef4444; font-weight: 600; margin-bottom: 1.4rem; }
  .notice { font-size: 0.92rem; line-height: 1.55; color: #94a3b8; margin-bottom: 1.4rem; background: rgba(0,0,0,0.25); border-radius: 8px; padding: 1rem; text-align: left; }
  .notice strong { color: #f8fafc; }
  .notice code { background: rgba(255,255,255,0.08); padding: 0.15rem 0.35rem; border-radius: 4px; color: #facc15; font-size: 0.85rem; }
  .user-pill { display: flex; align-items: center; justify-content: space-between; padding: 0.6rem 0.9rem; background: rgba(255,255,255,0.04); border: 1px solid var(--border, #243042); border-radius: 8px; font-size: 0.9rem; margin-bottom: 1.5rem; }
  .tag.bad { background: rgba(239,68,68,0.2); color: #f87171; padding: 0.2rem 0.5rem; border-radius: 4px; font-size: 0.75rem; font-weight: 600; }
  .actions { display: flex; flex-direction: column; gap: 0.75rem; }
  .btn { width: 100%; padding: 0.75rem 1rem; border-radius: 8px; font-weight: 600; font-size: 0.92rem; cursor: pointer; text-decoration: none; display: inline-flex; align-items: center; justify-content: center; border: 1px solid transparent; }
  .btn.primary { background: #3b82f6; color: #fff; }
  .btn.primary:hover { background: #2563eb; }
  .btn.outline { background: transparent; border-color: var(--border, #243042); color: #94a3b8; }
  .btn.outline:hover { color: #f8fafc; border-color: #475569; }
  .btn.text { background: transparent; color: #64748b; font-size: 0.85rem; border: none; padding: 0.4rem; }
  .btn.text:hover { color: #94a3b8; text-decoration: underline; }
</style>
