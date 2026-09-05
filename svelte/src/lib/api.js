export class ApiError extends Error {
  constructor(status, detail) {
    super(detail || `HTTP ${status}`);
    this.status = status;
    this.detail = detail;
  }
}

async function request(method, path, body) {
  const res = await fetch(path, {
    method,
    headers: body === undefined ? {} : { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
    credentials: 'same-origin'
  });
  if (res.status === 204) return null;
  const text = await res.text();
  let data = null;
  try {
    data = text ? JSON.parse(text) : null;
  } catch {
    data = text;
  }
  if (!res.ok) {
    const detail = data && typeof data === 'object' ? data.detail : data;
    throw new ApiError(res.status, typeof detail === 'string' ? detail : JSON.stringify(detail));
  }
  return data;
}

export const api = {
  get: (path, params) => request('GET', params ? `${path}?${new URLSearchParams(params)}` : path),
  post: (path, body) => request('POST', path, body ?? {}),
  put: (path, body) => request('PUT', path, body ?? {}),
  patch: (path, body) => request('PATCH', path, body ?? {}),
  del: (path) => request('DELETE', path)
};

export const admin = {
  get: (path, params) => api.get(`/api/admin${path}`, params),
  post: (path, body) => api.post(`/api/admin${path}`, body),
  put: (path, body) => api.put(`/api/admin${path}`, body),
  patch: (path, body) => api.patch(`/api/admin${path}`, body),
  del: (path) => api.del(`/api/admin${path}`)
};
