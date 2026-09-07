<script>
  import Icon from './Icon.svelte';

  let { text = '', label = 'Copy' } = $props();

  let done = $state(false);
  let timer = 0;

  async function copy() {
    try {
      if (navigator.clipboard && window.isSecureContext) {
        await navigator.clipboard.writeText(text);
      } else {
        const area = document.createElement('textarea');
        area.value = text;
        area.style.position = 'fixed';
        area.style.opacity = '0';
        document.body.append(area);
        area.select();
        document.execCommand('copy');
        area.remove();
      }
    } catch {
      return;
    }
    done = true;
    clearTimeout(timer);
    timer = setTimeout(() => (done = false), 1500);
  }
</script>

<button class="copy" class:done onclick={copy} title={label} aria-label={label}>
  <Icon name={done ? 'check' : 'copy'} size={13} />
</button>

<style>
  .copy {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    padding: 0.2rem;
    border: 1px solid transparent;
    border-radius: 5px;
    background: none;
    color: var(--muted);
    opacity: 0.75;
  }

  .copy:hover {
    opacity: 1;
    color: var(--accent);
    border-color: var(--border);
  }

  .copy.done {
    color: var(--ok);
    opacity: 1;
  }
</style>
