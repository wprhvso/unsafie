const ANSI_COLORS = {
  30: '#000000', 31: '#ef4444', 32: '#22c55e', 33: '#eab308',
  34: '#3b82f6', 35: '#a855f7', 36: '#06b6d4', 37: '#e2e8f0',
  90: '#64748b', 91: '#f87171', 92: '#4ade80', 93: '#facc15',
  94: '#60a5fa', 95: '#c084fc', 96: '#22d3ee', 97: '#ffffff',
};

const ANSI_BG_COLORS = {
  40: '#000000', 41: '#991b1b', 42: '#166534', 43: '#854d0e',
  44: '#1e40af', 45: '#6b21a8', 46: '#155e75', 47: '#cbd5e1',
  100: '#334155', 101: '#dc2626', 102: '#15803d', 103: '#a16207',
  104: '#1d4ed8', 105: '#7e22ce', 106: '#0e7490', 107: '#f8fafc',
};

function get256Color(n) {
  if (n < 8) return ANSI_COLORS[30 + n];
  if (n < 16) return ANSI_COLORS[90 + (n - 8)];
  if (n >= 16 && n <= 231) {
    n -= 16;
    const r = Math.floor(n / 36);
    const g = Math.floor((n % 36) / 6);
    const b = n % 6;
    const toVal = (v) => (v ? v * 40 + 55 : 0);
    return `rgb(${toVal(r)},${toVal(g)},${toVal(b)})`;
  }
  if (n >= 232 && n <= 255) {
    const c = (n - 232) * 10 + 8;
    return `rgb(${c},${c},${c})`;
  }
  return '';
}

export function ansiToHtml(str) {
  if (!str) return '';

  const clean = str
    .replace(/\r\n/g, '\n')
    .replace(/\r/g, '\n')
    .replace(/(?:\x1b|\u001b|ESC)\[[0-9;?]*[A-HJKSTfinu]/g, '');

  const escaped = clean
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;');

  let fg = '';
  let bg = '';
  let bold = false;
  let underline = false;
  let hasOpenSpan = false;

  const regex = /(?:\x1b|\u001b|ESC)\[([0-9;]*)m/g;
  let result = '';
  let lastIndex = 0;
  let match;

  while ((match = regex.exec(escaped)) !== null) {
    result += escaped.slice(lastIndex, match.index);
    lastIndex = regex.lastIndex;

    const codes = match[1] ? match[1].split(';').map(Number) : [0];

    for (let i = 0; i < codes.length; i++) {
      const code = codes[i];
      if (code === 0) {
        fg = '';
        bg = '';
        bold = false;
        underline = false;
      } else if (code === 1) {
        bold = true;
      } else if (code === 4) {
        underline = true;
      } else if (code === 22) {
        bold = false;
      } else if (code === 24) {
        underline = false;
      } else if (code === 39) {
        fg = '';
      } else if (code === 49) {
        bg = '';
      } else if (ANSI_COLORS[code]) {
        fg = ANSI_COLORS[code];
      } else if (ANSI_BG_COLORS[code]) {
        bg = ANSI_BG_COLORS[code];
      } else if (code === 38 && codes[i + 1] === 5 && codes[i + 2] !== undefined) {
        fg = get256Color(codes[i + 2]);
        i += 2;
      } else if (code === 48 && codes[i + 1] === 5 && codes[i + 2] !== undefined) {
        bg = get256Color(codes[i + 2]);
        i += 2;
      } else if (code === 38 && codes[i + 1] === 2 && codes[i + 4] !== undefined) {
        fg = `rgb(${codes[i + 2]},${codes[i + 3]},${codes[i + 4]})`;
        i += 4;
      } else if (code === 48 && codes[i + 1] === 2 && codes[i + 4] !== undefined) {
        bg = `rgb(${codes[i + 2]},${codes[i + 3]},${codes[i + 4]})`;
        i += 4;
      }
    }

    if (hasOpenSpan) {
      result += '</span>';
      hasOpenSpan = false;
    }

    const styles = [];
    if (fg) styles.push(`color:${fg}`);
    if (bg) styles.push(`background-color:${bg}`);
    if (bold) styles.push('font-weight:bold');
    if (underline) styles.push('text-decoration:underline');

    if (styles.length > 0) {
      result += `<span style="${styles.join(';')}">`;
      hasOpenSpan = true;
    }
  }

  result += escaped.slice(lastIndex);
  if (hasOpenSpan) {
    result += '</span>';
  }
  return result;
}
