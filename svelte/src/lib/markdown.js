/**
 * Rendering of a shared answer: markdown-it + highlight.js + KaTeX,
 * with a copy button on top of every code block.
 *
 * Everything heavy is imported lazily, so only the share route pays for it —
 * the admin bundle stays untouched.
 */

const MATH = {
  delimiters: [
    { left: '$$', right: '$$', display: true },
    { left: '\\[', right: '\\]', display: true },
    { left: '\\(', right: '\\)', display: false },
    { left: '$', right: '$', display: false }
  ],
  throwOnError: false,
  ignoredTags: ['script', 'noscript', 'style', 'textarea', 'pre', 'code']
};

const ICON_COPY =
  '<svg class="icon-copy" viewBox="0 0 16 16" aria-hidden="true"><path d="M0 6.75C0 5.784.784 5 1.75 5h1.5a.75.75 0 0 1 0 1.5h-1.5a.25.25 0 0 0-.25.25v7.5c0 .138.112.25.25.25h7.5a.25.25 0 0 0 .25-.25v-1.5a.75.75 0 0 1 1.5 0v1.5A1.75 1.75 0 0 1 9.25 16h-7.5A1.75 1.75 0 0 1 0 14.25Z"></path><path d="M5 1.75C5 .784 5.784 0 6.75 0h7.5C15.216 0 16 .784 16 1.75v7.5A1.75 1.75 0 0 1 14.25 11h-7.5A1.75 1.75 0 0 1 5 9.25Zm1.75-.25a.25.25 0 0 0-.25.25v7.5c0 .138.112.25.25.25h7.5a.25.25 0 0 0 .25-.25v-7.5a.25.25 0 0 0-.25-.25Z"></path></svg>';

const ICON_CHECK =
  '<svg class="icon-check" viewBox="0 0 16 16" aria-hidden="true"><path d="M13.78 4.22a.75.75 0 0 1 0 1.06l-7.25 7.25a.75.75 0 0 1-1.06 0L2.22 9.28a.751.751 0 0 1 .018-1.042.751.751 0 0 1 1.042-.018L6 10.94l6.72-6.72a.75.75 0 0 1 1.06 0Z"></path></svg>';

const COPIED_MS = 1600;

const FENCE = /^ {0,3}(?:`{3,}|~{3,})[ \t]*([^\s`{}]+)/gm;

/**
 * The common bundle of highlight.js knows the forty usual languages and is ten
 * times lighter than the full one; everything else — nix, dockerfile, elixir
 * and so on — is worth its megabyte only when the answer really mentions it.
 */
async function highlighter(source) {
  const { default: common } = await import('highlight.js/lib/common');
  const declared = new Set();
  for (const [, name] of source.matchAll(FENCE)) declared.add(name.toLowerCase());
  if ([...declared].every((name) => common.getLanguage(name))) return common;
  const { default: full } = await import('highlight.js');
  return full;
}

async function copyText(text) {
  if (navigator.clipboard && window.isSecureContext) {
    await navigator.clipboard.writeText(text);
    return;
  }
  const area = document.createElement('textarea');
  area.value = text;
  area.setAttribute('readonly', '');
  area.style.position = 'fixed';
  area.style.opacity = '0';
  document.body.append(area);
  area.select();
  let ok = false;
  try {
    ok = document.execCommand('copy');
  } catch {
    ok = false;
  }
  area.remove();
  if (!ok) throw new Error('copy failed');
}

function addCopyButtons(root, label) {
  for (const pre of root.querySelectorAll('pre')) {
    const block = document.createElement('div');
    block.className = 'code-block';
    pre.replaceWith(block);
    block.append(pre);

    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'code-copy';
    button.setAttribute('aria-label', label);
    button.innerHTML = ICON_COPY + ICON_CHECK;

    let timer = 0;
    button.addEventListener('click', async () => {
      const code = pre.querySelector('code');
      try {
        await copyText(code ? code.textContent : pre.textContent);
      } catch {
        return;
      }
      button.classList.add('copied');
      clearTimeout(timer);
      timer = setTimeout(() => button.classList.remove('copied'), COPIED_MS);
    });

    block.append(button);
  }
}

/** Markdown into a detached container, ready to be moved into the page. */
export async function render(source, { copyLabel = 'Copy' } = {}) {
  const [{ default: MarkdownIt }, { default: renderMath }, hljs] = await Promise.all([
    import('markdown-it'),
    import('katex/contrib/auto-render'),
    highlighter(source)
  ]);

  const md = new MarkdownIt({
    html: false,
    linkify: true,
    breaks: true,
    typographer: false,
    highlight: (code, language) => {
      const name = language && hljs.getLanguage(language) ? language : null;
      try {
        const result = name ? hljs.highlight(code, { language: name }) : hljs.highlightAuto(code);
        return `<pre><code class="hljs">${result.value}</code></pre>`;
      } catch {
        return '';
      }
    }
  });

  const holder = document.createElement('div');
  holder.innerHTML = md.render(source);
  renderMath(holder, MATH);
  addCopyButtons(holder, copyLabel);
  return holder;
}

/** Last resort when a chunk fails to load: the answer as plain text. */
export function plain(source) {
  const holder = document.createElement('div');
  const pre = document.createElement('pre');
  pre.textContent = source;
  holder.append(pre);
  return holder;
}
