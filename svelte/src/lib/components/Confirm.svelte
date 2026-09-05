<script>
  let { label = 'Delete', question = 'Are you sure?', tone = 'danger', onconfirm } = $props();
  let asking = $state(false);
  let busy = $state(false);

  async function go() {
    busy = true;
    try {
      await onconfirm();
      asking = false;
    } finally {
      busy = false;
    }
  }
</script>

{#if asking}
  <span class="row small">
    <span class="muted">{question}</span>
    <button class={tone} disabled={busy} onclick={go}>{busy ? '…' : 'Yes'}</button>
    <button disabled={busy} onclick={() => (asking = false)}>No</button>
  </span>
{:else}
  <button class={tone} onclick={() => (asking = true)}>{label}</button>
{/if}
