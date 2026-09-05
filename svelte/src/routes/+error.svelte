<script>
  import { page } from '$app/state';
</script>

<svelte:head><title>unsafie — {page.status}</title></svelte:head>

<main>
  <h1>{page.status}</h1>
  <p class="muted">This page does not exist.</p>
  <p class="small"><a href="/admin">Go to the admin panel</a></p>
</main>

<style>
  main { max-width: 30rem; margin: 20vh auto 0; padding: 0 1rem; text-align: center; }
  h1 { font-size: 3rem; margin-bottom: .2rem; }
</style>
