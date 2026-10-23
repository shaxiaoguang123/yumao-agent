export function createLiveAvailabilityApi(client) {
  if (typeof client?.request !== 'function') {
    throw new TypeError('an authenticated HTTP client is required');
  }
  return {
    options() {
      return client.request('/api/availability/live/options');
    },
    categories(credentialId, options = {}) {
      return client.request('/api/availability/live/categories', {
        timeoutMs: 15_000,
        ...options,
        method: 'POST',
        body: { credential_id: credentialId },
      });
    },
    grid({ credentialId, scopeReference, targetDate }, options = {}) {
      return client.request('/api/availability/live/grid', {
        timeoutMs: 15_000,
        ...options,
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
