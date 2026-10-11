export function createAvailabilitySimulationApi(client) {
  if (typeof client?.request !== 'function') throw new TypeError('an authenticated HTTP client is required');
  return {
    options: () => client.request('/api/availability/simulation/options'),
    gridPreview: (body) => client.request('/api/availability/simulation/grid', { method:'POST', body }),
    historyPreview: (response) => client.request('/api/availability/history/preview', { method:'POST', body:{response} }),
    match: (planId, base_version, scenario) => client.request(`/api/availability/simulation/plans/${encodeURIComponent(planId)}`, {
      method: 'POST', body: { base_version, scenario },
    }),
  };
}
