const path = (id) => `/api/plans/${encodeURIComponent(id)}`;
const scopedPath = (base, credential_id) => {
  if (credential_id === undefined || credential_id === null || credential_id === '') return base;
  const query = new URLSearchParams({credential_id});
  return `${base}?${query}`;
};
const scopedBody = (body, credential_id) => credential_id === undefined ? body : {...body,credential_id};
export function createPlanApi(client) {
  if (typeof client?.request !== 'function') throw new TypeError('an authenticated HTTP client is required');
  return {
    remove: (id, base_version, credential_id) => client.request(path(id), {method:'DELETE',body:scopedBody({base_version},credential_id)}),
    removeQueue: (date, base_version, credential_id) => client.request(`/api/plans/manual-queues/${encodeURIComponent(date)}`, {method:'DELETE',body:scopedBody({base_version},credential_id)}),
    queues: (credential_id) => client.request(scopedPath('/api/plans/manual-queues',credential_id)),
    queue: (date, credential_id) => client.request(scopedPath(`/api/plans/manual-queues/${encodeURIComponent(date)}`,credential_id)),
    saveQueue: (date, base_version, entries, credential_id) => client.request(`/api/plans/manual-queues/${encodeURIComponent(date)}`, {method:'PUT',body:scopedBody({base_version,entries},credential_id)}),
    queueRevisions: (date, credential_id) => client.request(scopedPath(`/api/plans/manual-queues/${encodeURIComponent(date)}/revisions`,credential_id)),
    executionQueue: (date, credential_id) => client.request(
      `/api/booking-execution/credentials/${encodeURIComponent(credential_id)}/queues/${encodeURIComponent(date)}`,
    ),
    list: (credential_id) => client.request(scopedPath('/api/plans',credential_id)),
    options: () => client.request('/api/plans/options'),
    get: (id, credential_id) => client.request(scopedPath(path(id),credential_id)),
    create: (intent, credential_id) => client.request('/api/plans', { method:'POST', body:scopedBody({intent},credential_id) }),
    update: (id, base_version, intent, credential_id) => client.request(path(id), { method:'PATCH', body:scopedBody({base_version,intent},credential_id) }),
    revisions: (id, credential_id) => client.request(scopedPath(`${path(id)}/revisions`,credential_id)),
    window: (date, planId) => {
      const query = new URLSearchParams();
      if (date) query.set('target_date',date);
      if (planId) query.set('plan_id',planId);
      return client.request(`/api/booking-window${query.size ? `?${query}` : ''}`);
    },
  };
}
