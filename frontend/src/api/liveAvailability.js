export function createLiveAvailabilityApi(client) {
  if (typeof client?.request !== 'function') {
    throw new TypeError('an authenticated HTTP client is required');
  }
  return {
    options() {
      return client.request('/api/availability/live/options');
    },
    categories(credentialId) {
      return client.request('/api/availability/live/categories', {
        method: 'POST',
        body: { credential_id: credentialId },
      });
    },
    grid({ credentialId, scopeReference, targetDate }) {
      return client.request('/api/availability/live/grid', {
        method: 'POST',
        body: {
          credential_id: credentialId,
          scope_reference: scopeReference,
          target_date: targetDate,
        },
      });
    },
  };
}
