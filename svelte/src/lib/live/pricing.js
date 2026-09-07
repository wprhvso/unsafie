const MILLION = 1_000_000;
const CACHE_WRITE = 2.0;
const CACHE_READ = 0.1;

const MODELS = [
  { prefix: 'claude-mythos-5', input: 10, output: 50, context: 1_000_000 },
  { prefix: 'claude-fable-5', input: 10, output: 50, context: 1_000_000 },
  { prefix: 'claude-opus-5', input: 5, output: 25, context: 1_000_000 },
  { prefix: 'claude-opus-4-7', input: 5, output: 25, context: 1_000_000 },
  { prefix: 'claude-opus-4-8', input: 5, output: 25, context: 1_000_000 },
  { prefix: 'claude-opus-4', input: 5, output: 25, context: 200_000 },
  { prefix: 'claude-sonnet-5', input: 2, output: 10, context: 1_000_000 },
  { prefix: 'claude-sonnet-4-6', input: 3, output: 15, context: 1_000_000 },
  { prefix: 'claude-sonnet-4', input: 3, output: 15, context: 200_000 },
  { prefix: 'claude-haiku-4', input: 1, output: 5, context: 200_000 }
];

const FALLBACK = { input: 5, output: 25, context: 200_000 };

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
  const billable =
    (usage?.input_tokens ?? 0) +
    (usage?.cache_creation_input_tokens ?? 0) * CACHE_WRITE +
    (usage?.cache_read_input_tokens ?? 0) * CACHE_READ;
  return (billable * price.input + (usage?.output_tokens ?? 0) * price.output) / MILLION;
}

export function contextOf(usage) {
  return (
    (usage?.input_tokens ?? 0) +
    (usage?.cache_read_input_tokens ?? 0) +
    (usage?.cache_creation_input_tokens ?? 0) +
    (usage?.output_tokens ?? 0)
  );
}
