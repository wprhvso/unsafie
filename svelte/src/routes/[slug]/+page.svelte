<script>
  import { page } from '$app/state';

  import Answer from '$lib/components/Answer.svelte';
  import Turn from '$lib/components/live/Turn.svelte';
  import Telemetry from '$lib/components/live/Telemetry.svelte';
  import CiRun from '$lib/components/live/CiRun.svelte';

  function payload() {
    const el = typeof document === 'undefined' ? null : document.getElementById('payload');
    if (!el) return null;
    try {
      return JSON.parse(el.textContent);
    } catch {
      return null;
    }
  }

  let data = $state(payload());
  let slug = $derived(data?.slug ?? page.params.slug);

  $effect(() => {
    const currentSlug = page.params.slug;
    const initial = payload();
    if (initial && initial.slug === currentSlug) {
      data = initial;
    } else if (currentSlug) {
      fetch(`/api/pages/${currentSlug}`)
        .then((res) => (res.ok ? res.json() : null))
        .then((json) => {
          if (json) data = json;
        })
        .catch(() => {});
    }
  });
</script>

{#if data?.kind === 'turn'}
  <Turn token={slug} telemetrySlug={data?.telemetry_slug} />
{:else if data?.kind === 'telemetry'}
  <Telemetry token={slug} />
{:else if data?.kind === 'ci'}
  <div class="ci-page-pad">
    <CiRun runId={data?.run_id} />
  </div>
{:else}
  <Answer content={typeof data?.content === 'string' ? data.content : null} title={data?.title} />
{/if}

<style>
  .ci-page-pad {
    padding: 1rem 1.5rem;
  }
</style>