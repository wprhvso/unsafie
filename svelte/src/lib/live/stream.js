import { ApiError, api } from '$lib/api.js';

const RETRY_MIN = 800;
const RETRY_MAX = 15000;
const OVER = ['done', 'failed'];

/**
 * Follow one turn: replay what already happened, then stay on the wire.
 *
 * The snapshot comes over plain HTTP, the tail over SSE. Frames carry their
 * stream id, so a dropped connection resumes exactly where it stopped instead of
 * replaying the whole turn. A turn that is already over is never followed.
 */
export function watch(token, { onSnapshot, onFrame, onStatus, onGap } = {}) {
  let source = null;
  let stopped = false;
  let finished = false;
  let after = null;
  let attempt = 0;
  let timer = 0;

  const status = (value, detail) => onStatus?.(value, detail);

  const feed = (frame) => {
    if (!frame || typeof frame !== 'object') return;
    if (frame.id) after = frame.id;
    if (frame.kind === 'turn.end') finished = true;
    onFrame?.(frame);
  };

  function drop() {
    if (source) {
      source.onerror = null;
      source.close();
      source = null;
    }
  }

  function halt(value) {
    stopped = true;
    clearTimeout(timer);
    drop();
    status(value);
  }

  async function snapshot() {
    const data = await api.get(`/api/live/${token}`, after ? { after } : undefined);
    onSnapshot?.(data);
    for (const frame of data.events ?? []) feed(frame);
    return data;
  }

  function over(data) {
    return finished || OVER.includes(data?.turn?.status);
  }

  function retry() {
    if (stopped) return;
    attempt += 1;
    const wait = Math.min(RETRY_MAX, RETRY_MIN * 2 ** (attempt - 1));
    status('reconnecting');
    clearTimeout(timer);
    timer = setTimeout(open, wait);
  }

  async function recover() {
    drop();
    // EventSource hides the status code, so ask the plain endpoint what happened.
    let data;
    try {
      data = await snapshot();
    } catch (e) {
      if (e instanceof ApiError && e.status === 404) return halt('gone');
      return retry();
    }
    if (over(data)) return halt('done');
    retry();
  }

  function open() {
    if (stopped) return;
    drop();
    const query = after ? `?after=${encodeURIComponent(after)}` : '';
    source = new EventSource(`/api/live/${token}/stream${query}`);
    source.onopen = () => {
      attempt = 0;
      status('live');
    };
    source.onmessage = (event) => {
      try {
        feed(JSON.parse(event.data));
      } catch {
        /* a half-written frame; the next one will do */
      }
      if (finished) halt('done');
    };
    source.addEventListener('gap', () => onGap?.());
    source.addEventListener('done', () => halt('done'));
    source.onerror = () => {
      if (!stopped) void recover();
    };
  }

  (async () => {
    status('loading');
    let data;
    try {
      data = await snapshot();
    } catch (e) {
      if (e instanceof ApiError && e.status === 404) return halt('gone');
      return halt('error');
    }
    if (over(data)) return halt('done');
    open();
  })();

  return () => {
    stopped = true;
    clearTimeout(timer);
    drop();
  };
}
