<script>
  import { admin } from '$lib/api.js';
  import { resource } from '$lib/resource.svelte.js';
  import { UNITS_PER_USD } from '$lib/format.js';
  import Panel from '$lib/components/Panel.svelte';
  import Loader from '$lib/components/Loader.svelte';

  const config = resource(() => admin.get('/config'));
  let ratio = $state(null);
  let oauth = $state(null);
  let busy = $state(false);
  let saved = $state('');
  let error = $state('');

  $effect(() => {
    if (config.data && ratio === null) {
      ratio = config.data.ratio;
      oauth = config.data.oauth_ratio;
    }
  });

  async function save() {
    busy = true;
    error = '';
    saved = '';
    try {
      await admin.put('/config', { ratio: Number(ratio), oauth_ratio: Number(oauth) });
      await config.reload();
      saved = 'Saved.';
    } catch (e) {
      error = e.message;
    } finally {
      busy = false;
    }
  }
</script>

<svelte:head><title>unsafie — pricing</title></svelte:head>
<h1>Pricing</h1>

<Loader state={config}>
  <Panel title="Multipliers">
    <div class="pad stack">
      <p class="muted small">
        A turn costing <b>$1</b> of real Anthropic spend is charged to the user as
        <b>{Math.round(Number(ratio) * UNITS_PER_USD).toLocaleString()}</b> units on an api_key,
        <b>{Math.round(Number(oauth) * UNITS_PER_USD).toLocaleString()}</b> units on an oauth key
        ({UNITS_PER_USD.toLocaleString()} units = $1).
      </p>
      <label class="row">
        <span class="w">api_key ratio</span>
        <input type="number" step="0.05" min="0" bind:value={ratio} disabled={busy} />
      </label>
      <label class="row">
        <span class="w">oauth ratio</span>
        <input type="number" step="0.05" min="0" bind:value={oauth} disabled={busy} />
      </label>
      <div class="row">
        <button onclick={save} disabled={busy}>Save</button>
        {#if saved}<span class="ok small">{saved}</span>{/if}
        {#if error}<span class="err small">{error}</span>{/if}
      </div>
    </div>
  </Panel>
</Loader>

<style>
  .pad { padding: 1rem; }
  .w { width: 8rem; color: var(--muted); }
  .ok { color: var(--ok); }
  .err { color: var(--bad); }
</style>
