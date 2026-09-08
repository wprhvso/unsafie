const MILLION = 1_000_000;

const MODELS = [
  { prefix: 'gemini-3.1-pro-preview', input: 1.25, output: 5.0, context: 1_000_000 },
  { prefix: 'gemini-3-flash-preview', input: 0.15, output: 0.6, context: 1_000_000 },
  { prefix: 'gemini-3.1-flash-lite', input: 0.075, output: 0.3, context: 1_000_000 },
  { prefix: 'gemini-2.5-pro', input: 1.25, output: 5.0, context: 1_000_000 },
  { prefix: 'gemini-2.5-flash', input: 0.15, output: 0.6, context: 1_000_000 }
];

const FALLBACK = { input: 0.5, output: 2.0, context: 1_000_000 };

export function priceOf(model) {
  const name = String(model ?? '').toLowerCase();
  let best = FALLBACK;
  let length = 0;
  for (const row of MODELS) {
    if (name.startsWith(row.prefix) && row.prefix.length > length) {
      best = row;
      length = row.prefix.length;
    }
  }
  return best;
}

export function contextLimit(model) {
  return priceOf(model).context;
}

export function costOf(usage, model) {
  const price = priceOf(model);
  const inputs = Number(usage?.input_tokens ?? 0);
  const output = Number(usage?.output_tokens ?? 0);
  return (inputs * price.input + output * price.output) / MILLION;
}

export function contextOf(usage) {
  return Number(usage?.total_tokens ?? (Number(usage?.input_tokens ?? 0) + Number(usage?.output_tokens ?? 0)));
}
