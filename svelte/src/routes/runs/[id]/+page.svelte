<script>
  import { onMount } from 'svelte';
  import { page } from '$app/state';
  import { goto } from '$app/navigation';

  onMount(() => {
    goto(`/ci/runs/${page.params.id}`, { replaceState: true });
  });
</script>

<p class="muted center">Redirecting to run…</p>

<style>
  .center { text-align: center; margin-top: 25vh; color: #94a3b8; }
</style>
