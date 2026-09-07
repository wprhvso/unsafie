<script>
  import { ICONS } from './icons.js';

  let { name, size = 16 } = $props();

  const paths = $derived(ICONS[name] ?? ICONS.note);
</script>

<svg
  viewBox="0 0 24 24"
  width={size}
  height={size}
  fill="none"
  stroke="currentColor"
  stroke-width="2"
  stroke-linecap="round"
  stroke-linejoin="round"
  aria-hidden="true"
>
  {#each paths as d (d)}<path {d} />{/each}
</svg>

<style>
  svg {
    display: block;
    flex: 0 0 auto;
  }
</style>
