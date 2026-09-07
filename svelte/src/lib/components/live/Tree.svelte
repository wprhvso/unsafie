<script>
  import Self from './Tree.svelte';

  let { value, label = null, depth = 0, last = true } = $props();

  const LONG = 400;

  const kind = $derived(
    value === null || value === undefined
      ? 'empty'
      : Array.isArray(value)
        ? 'array'
        : typeof value === 'object'
          ? 'object'
          : typeof value
  );
  const branch = $derived(kind === 'array' || kind === 'object');
  const entries = $derived(
    kind === 'array'
      ? value.map((item, i) => [String(i), item])
      : kind === 'object'
        ? Object.entries(value)
        : []
  );
  const block = $derived(kind === 'string' && (value.includes('\n') || value.length > 120));

  let open = $state(depth < 2);
  let whole = $state(false);

  const brief = $derived(
    kind === 'array' ? `[ ${entries.length} ]` : `{ ${entries.length} }`
  );
  const text = $derived(
    kind === 'string' && !whole && value.length > LONG ? value.slice(0, LONG) : value
  );
</script>

<div class="node" class:last>
  {#if branch}
    <button class="row toggle" onclick={() => (open = !open)}>
      <span class="caret" class:open>▸</span>
      {#if label !== null}<span class="key">{label}</span><span class="colon">:</span>{/if}
      <span class="brief">{brief}</span>
    </button>
    {#if open && entries.length}
      <div class="children">
        {#each entries as [name, item], i (name)}
          <Self value={item} label={name} depth={depth + 1} last={i === entries.length - 1} />
        {/each}
      </div>
    {/if}
  {:else if block}
    <div class="row">
      {#if label !== null}<span class="key">{label}</span><span class="colon">:</span>{/if}
      <span class="muted tiny">{value.length.toLocaleString()} chars</span>
    </div>
    <pre class="text">{text}{#if !whole && value.length > LONG}…{/if}</pre>
    {#if value.length > LONG}
      <button class="more" onclick={() => (whole = !whole)}>
        {whole ? 'collapse' : `show all ${value.length.toLocaleString()} chars`}
      </button>
    {/if}
  {:else}
    <div class="row">
      {#if label !== null}<span class="key">{label}</span><span class="colon">:</span>{/if}
      <span class="value {kind}">
        {kind === 'empty' ? 'null' : kind === 'string' ? `"${value}"` : String(value)}
      </span>
    </div>
  {/if}
</div>

<style>
  .node {
    font-family: var(--mono);
    font-size: 0.82rem;
    line-height: 1.6;
  }

  .row {
    display: flex;
    align-items: baseline;
    gap: 0.3rem;
    flex-wrap: wrap;
    min-width: 0;
  }

  button.row {
    padding: 0;
    border: 0;
    background: none;
    color: inherit;
    text-align: left;
    width: 100%;
    cursor: pointer;
  }

  button.row:hover {
    color: inherit;
  }

  button.row:hover .key,
  button.row:hover .brief {
    color: var(--accent);
  }

  .caret {
    display: inline-block;
    color: var(--muted);
    transition: transform 0.12s ease;
    font-size: 0.7rem;
  }

  .caret.open {
    transform: rotate(90deg);
  }

  .key {
    color: var(--live-key);
  }

  .colon {
    color: var(--muted);
    margin-left: -0.2rem;
  }

  .brief {
    color: var(--muted);
  }

  .children {
    padding-left: 0.85rem;
    margin-left: 0.25rem;
    border-left: 1px solid var(--border);
  }

  .value {
    overflow-wrap: anywhere;
  }

  .value.string {
    color: var(--live-string);
  }

  .value.number {
    color: var(--live-number);
  }

  .value.boolean,
  .value.empty {
    color: var(--live-atom);
  }

  .text {
    margin: 0.15rem 0 0;
    padding: 0.5rem 0.6rem;
    background: var(--live-sunken);
    border: 1px solid var(--border);
    border-radius: 6px;
    white-space: pre-wrap;
    overflow-wrap: anywhere;
    color: var(--live-string);
    max-height: 26rem;
    overflow: auto;
  }

  .more {
    margin-top: 0.25rem;
    padding: 0.1rem 0.4rem;
    font-size: 0.75rem;
    border: 0;
    background: none;
    color: var(--muted);
  }

  .tiny {
    font-size: 0.72rem;
  }
</style>
