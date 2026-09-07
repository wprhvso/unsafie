const MILLION = 1_000_000;

const TABLE = [
  { match: /opus/, input: 15, output: 75, write: 18.75, read: 1.5, context: 200_000 },
  { match: /haiku-4|haiku-4-5|haiku4/, input: 1, output: 5, write: 1.25, read: 0.1, context: 200_000 },
  { match: /haiku/, input: 0.8, output: 4, write: 1, read: 0.08, context: 200_000 },
  { match: /sonnet/, input: 3, output: 15, write: 3.75, read: 0.3, context: 200_000 }
];

const FALLBACK = { input: 3, output: 15, write: 3.75, read: 0.3, context: 200_000 };

export function priceOf(model) {
  const name = String(model ?? '').toLowerCase();
  return TABLE.find((row) => row.match.test(name)) ?? FALLBACK;
}

export function contextLimit(model) {
  return priceOf(model).context;
}

export function costOf(usage, model) {
  const price = priceOf(model);
  const input = usage?.input_tokens ?? 0;
  const output = usage?.output_tokens ?? 0;
  const read = usage?.cache_read_input_tokens ?? 0;
  const write = usage?.cache_creation_input_tokens ?? 0;
  return (
    (input * price.input + output * price.output + read * price.read + write * price.write) / MILLION
  );
}

export function contextOf(usage) {
  return (
    (usage?.input_tokens ?? 0) +
    (usage?.cache_read_input_tokens ?? 0) +
    (usage?.cache_creation_input_tokens ?? 0) +
    (usage?.output_tokens ?? 0)
  );
}
