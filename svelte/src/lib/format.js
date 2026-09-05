export const UNITS_PER_USD = 10000;

export function money(units) {
  if (units === null || units === undefined) return '—';
  return `$${(units / UNITS_PER_USD).toFixed(2)}`;
}

export function usd(value) {
  if (value === null || value === undefined) return '—';
  return `$${Number(value).toFixed(4)}`;
}

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
