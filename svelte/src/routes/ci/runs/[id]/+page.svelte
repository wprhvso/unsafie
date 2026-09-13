<script>
  import { page } from '$app/state';
  import CiRun from '$lib/components/live/CiRun.svelte';
</script>

<CiRun runId={page.params.id} />
