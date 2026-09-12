export function when(iso) {
  if (!iso) return '—';
  const d = new Date(iso);
  if (Number.isNaN(+d)) return String(iso);
  return d.toLocaleString(undefined, { dateStyle: 'short', timeStyle: 'short' });
}

export function ago(iso) {
  if (!iso) return '—';
  const seconds = (Date.now() - new Date(iso)) / 1000;
  const abs = Math.abs(seconds);
  const [value, unit] =
    abs < 60 ? [seconds, 'second'] :
    abs < 3600 ? [seconds / 60, 'minute'] :
    abs < 86400 ? [seconds / 3600, 'hour'] :
    [seconds / 86400, 'day'];
  return new Intl.RelativeTimeFormat(undefined, { numeric: 'auto' })
    .format(-Math.round(value), unit);
}

export function duration(seconds) {
  if (!seconds && seconds !== 0) return '—';
  const s = Math.round(seconds);
  if (s < 60) return `${s}s`;
  const parts = [];
  for (const [name, size] of [['d', 86400], ['h', 3600], ['m', 60]]) {
    const n = Math.floor((s % (size * (name === 'd' ? 1e9 : name === 'h' ? 24 : 60))) / size);
    if (n) parts.push(`${n}${name}`);
  }
  return parts.join(' ') || '0m';
}

export function bytes(n) {
  if (!n) return '0 B';
  const units = ['B', 'KB', 'MB', 'GB'];
  let value = n;
  let i = 0;
  while (value >= 1024 && i < units.length - 1) {
    value /= 1024;
    i += 1;
  }
  return `${i === 0 ? value : value.toFixed(1)} ${units[i]}`;
}

export function short(text, limit = 80) {
  if (!text) return '';
  const one = String(text).replace(/\s+/g, ' ').trim();
  return one.length > limit ? `${one.slice(0, limit)}…` : one;
}

export function money() {
  return '';
}

export function usd() {
  return '';
}


export function highlightJson(input) {
  let str = input;
  if (typeof str !== 'string') {
    try {
      str = JSON.stringify(str, null, 2);
    } catch {
      str = String(str);
    }
  } else {
    try {
      str = JSON.stringify(JSON.parse(str), null, 2);
    } catch {
      // keep raw string
    }
  }

  const escaped = String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;');

  return escaped.replace(
    /("(\\u[a-zA-Z0-9]{4}|\\[^u]|[^\\"])*"(\s*:)?|\b(true|false|null)\b|-?\d+(?:\.\d*)?(?:[eE][+\-]?\d+)?)/g,
    (match) => {
      let cls = 'hl-number';
      if (/^"/.test(match)) {
        if (/:$/.test(match)) {
          cls = 'hl-key';
          return `<span class="${cls}">${match.slice(0, -1)}</span>:`;
        }
        cls = 'hl-string';
      } else if (/true|false/.test(match)) {
        cls = 'hl-boolean';
      } else if (/null/.test(match)) {
        cls = 'hl-null';
      }
      return `<span class="${cls}">${match}</span>`;
    }
  );
}
