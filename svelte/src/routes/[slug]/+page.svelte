<script>
  import { page } from '$app/state';

  import Answer from '$lib/components/Answer.svelte';
  import Turn from '$lib/components/live/Turn.svelte';
  import Telemetry from '$lib/components/live/Telemetry.svelte';

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
{:else if data?.kind === 'desktop'}
  <iframe
    src={`/kasmvnc/index.html?path=api/m/${slug}/stream&autoconnect=1&resize=remote`}
    title={data?.title || 'Desktop'}
    class="kasm-frame"
    allow="clipboard-read; clipboard-write; fullscreen"
  ></iframe>
{:else}
  <Answer content={typeof data?.content === 'string' ? data.content : null} title={data?.title} />
{/if}

<style>
  :global(body:has(.kasm-frame), html:has(.kasm-frame)) {
    margin: 0;
    padding: 0;
    height: 100%;
    overflow: hidden;
    background: #0b0d10;
  }
  .kasm-frame {
    width: 100vw;
    height: 100vh;
    border: none;
    display: block;
  }
</style>
