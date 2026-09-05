import { ApiError } from '$lib/api.js';

/** Reactive wrapper around an async loader: state.data / .loading / .error / .empty. */
export function resource(loader, { auto = true } = {}) {
  const state = $state({ data: null, loading: false, error: null });

  async function reload(...args) {
    state.loading = true;
    state.error = null;
    try {
      state.data = await loader(...args);
    } catch (e) {
      state.error = e instanceof ApiError ? `${e.status}: ${e.message}` : String(e);
      if (e instanceof ApiError && e.status === 401) {
        location.href = '/login';
      }
    } finally {
      state.loading = false;
    }
  }

  if (auto) reload();

  return {
    get data() { return state.data; },
    get loading() { return state.loading; },
    get error() { return state.error; },
    get empty() {
      const d = state.data;
      if (d === null || d === undefined) return !state.loading;
      if (Array.isArray(d)) return d.length === 0;
      if (typeof d === 'object' && Array.isArray(d.items)) return d.items.length === 0;
      return false;
    },
    reload
  };
}
