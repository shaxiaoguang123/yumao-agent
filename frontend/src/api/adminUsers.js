export function createAdminUsersApi(client) {
  if (typeof client?.request !== 'function') {
    throw new TypeError('an authenticated HTTP client is required');
  }

  return {
    list({ q = '', role = 'all', status = 'all', limit = 50, offset = 0 } = {}) {
      const params = new URLSearchParams({ role, status, limit: String(limit), offset: String(offset) });
      if (q.trim()) params.set('q', q.trim());
      return client.request(`/api/admin/users?${params.toString()}`);
    },
    disable(userId) {
      return client.request(`/api/admin/users/${encodeURIComponent(userId)}/disable`, {
        method: 'POST',
        body: {},
      });
    },
    enable(userId) {
      return client.request(`/api/admin/users/${encodeURIComponent(userId)}/enable`, {
        method: 'POST',
        body: {},
      });
    },
  };
}
