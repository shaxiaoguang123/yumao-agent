const path = (id) => `/api/plans/${encodeURIComponent(id)}`;
export function createPlanApi(client) {
  if (typeof client?.request !== 'function') throw new TypeError('an authenticated HTTP client is required');
  return {
    list: () => client.request('/api/plans'),
    options: () => client.request('/api/plans/options'),
    get: (id) => client.request(path(id)),
    create: (intent) => client.request('/api/plans', { method:'POST', body:{intent} }),
    update: (id, base_version, intent) => client.request(path(id), { method:'PATCH', body:{base_version,intent} }),
    revisions: (id) => client.request(`${path(id)}/revisions`),
    window: (date, planId) => {
      const query = new URLSearchParams();
      if (date) query.set('target_date',date);
      if (planId) query.set('plan_id',planId);
      return client.request(`/api/booking-window${query.size ? `?${query}` : ''}`);
    },
  };
}
