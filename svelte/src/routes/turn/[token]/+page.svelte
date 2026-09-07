<script>
  import { page } from '$app/state';
  import Turn from '$lib/components/live/Turn.svelte';
</script>

<Turn token={page.params.token} />
