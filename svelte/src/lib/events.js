import { browser } from '$app/environment';

/** Subscribe to the server event stream. Returns a stop function. */
export function subscribe({ kinds, match, onEvent, onGap } = {}) {
  if (!browser) return () => {};
  const params = new URLSearchParams();
  if (kinds?.length) params.set('kinds', kinds.join(','));
  if (match) params.set('match', Object.entries(match).map(([k, v]) => `${k}=${v}`).join(','));
  const source = new EventSource(`/api/admin/events?${params}`);
  const handler = (e) => {
    try {
      onEvent?.(JSON.parse(e.data));
    } catch {
      /* keepalive comments and malformed frames are ignored */
    }
  };
  source.addEventListener('message', handler);
  source.addEventListener('gap', () => onGap?.());
  for (const kind of kinds ?? []) {
    if (!kind.includes('*')) source.addEventListener(kind, handler);
  }
  if (kinds?.length) {
    const wild = new Set();
    source.onmessage = handler;
    void wild;
  }
  return () => source.close();
}

/** Re-run `load` at most once per `ms`, triggered by matching events. */
export function refreshOn(kinds, load, ms = 700) {
  let timer = null;
  return subscribe({
    kinds,
    onEvent: () => {
      if (timer) return;
      timer = setTimeout(() => {
        timer = null;
        load();
      }, ms);
    },
    onGap: load
  });
}
