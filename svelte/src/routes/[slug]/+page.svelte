<script>
  import { page } from '$app/state';

  import Answer from '$lib/components/Answer.svelte';
  import Turn from '$lib/components/live/Turn.svelte';

  function payload() {
    const el = typeof document === 'undefined' ? null : document.getElementById('payload');
    if (!el) return null;
    try {
      return JSON.parse(el.textContent);
    } catch {
      return null;
    }
  }

  const data = payload();
  const slug = data?.slug ?? page.params.slug;
</script>

{#if data?.kind === 'turn'}
  <Turn token={slug} />
{:else}
  <Answer content={typeof data?.content === 'string' ? data.content : null} title={data?.title} />
{/if}
