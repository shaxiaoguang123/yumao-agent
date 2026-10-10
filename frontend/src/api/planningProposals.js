export function createPlanningProposalApi(client) {
  if (typeof client?.request !== 'function') throw new TypeError('an authenticated HTTP client is required');
  return {
    generate: (message, plan_id, base_version) => client.request('/api/planning/proposals', {
      method:'POST', body:{message,plan_id,base_version},
    }),
  };
}
