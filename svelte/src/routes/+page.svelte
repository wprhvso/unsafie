<script>
  import { onMount } from 'svelte';
  import { goto } from '$app/navigation';
  import { api } from '$lib/api.js';

  onMount(async () => {
    try {
      const session = await api.get('/api/session');
      await goto(session?.ok ? '/admin' : '/login', { replaceState: true });
    } catch {
      await goto('/login', { replaceState: true });
    }
  });
</script>

<p class="muted center">…</p>

<style>
  .center { text-align: center; margin-top: 25vh; }
</style>
