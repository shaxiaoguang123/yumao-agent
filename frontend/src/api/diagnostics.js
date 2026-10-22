export function createDiagnosticsApi(client) {
  if (typeof client?.request !== 'function') throw new TypeError('an authenticated HTTP client is required');
  return {
    overview: (options = {}) => client.request('/api/metrics/overview', options),
    system: (options = {}) => client.request('/api/admin/metrics', options),
    logs(filters = {}, options = {}) {
      const params = new URLSearchParams();
      for (const key of ['hours', 'since', 'until', 'level', 'module', 'user_id', 'code', 'request_id', 'conversation_id', 'run_id', 'before', 'limit']) {
        if (filters[key] !== undefined && filters[key] !== null && filters[key] !== '') params.set(key, String(filters[key]));
      }
      return client.request(`/api/admin/logs?${params}`, options);
    },
    detail: (id, options = {}) => client.request(`/api/admin/logs/${encodeURIComponent(id)}`, options),
  };
}
