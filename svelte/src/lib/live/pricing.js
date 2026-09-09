const MODELS = [
  { prefix: 'gemini-3.1-pro-preview', context: 1_000_000 },
  { prefix: 'gemini-3-flash-preview', context: 1_000_000 },
  { prefix: 'gemini-3.1-flash-lite', context: 1_000_000 },
  { prefix: 'gemini-2.5-pro', context: 1_000_000 },
  { prefix: 'gemini-2.5-flash', context: 1_000_000 }
];

const FALLBACK = { context: 1_000_000 };

export function contextLimit(model) {
  const name = String(model ?? '').toLowerCase();
  for (const row of MODELS) {
    if (name.startsWith(row.prefix)) return row.context;
  }
  return FALLBACK.context;
}

export function costOf() {
  return 0;
}

export function contextOf(usage) {
  return (
    Number(usage?.input_tokens ?? 0) +
    Number(usage?.output_tokens ?? 0)
  );
}
