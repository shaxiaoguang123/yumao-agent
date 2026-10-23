function credentialPath(credentialId) {
  return `/api/credentials/${encodeURIComponent(credentialId)}`;
}

export function createCredentialApi(client) {
  if (typeof client?.request !== 'function') {
    throw new TypeError('an authenticated HTTP client is required');
  }
  let pending, snapshot, readEpoch = 0;
  const owner = () => `${client.user?.user_id || ''}\u0000${client.csrfToken || ''}\u0000${client.invalidationEpoch || 0}`;
  function invalidate() { readEpoch++; pending = null; snapshot = null; }
  const mutate = (path, options) => { invalidate(); return client.request(path, options).finally(invalidate); };
  return {
    list({ reuse = false } = {}) {
      const scope = owner(), now = Date.now();
      if (pending?.scope === scope) return pending.promise;
      if (reuse && snapshot?.scope === scope && now - snapshot.at >= 0 && now - snapshot.at < 5000) return Promise.resolve(snapshot.value);
      snapshot = null;
      const epoch = readEpoch;
      const request = { scope, promise: null };
      request.promise = client.request('/api/credentials').then(value => {
        if (epoch === readEpoch && scope === owner()) snapshot = { scope, at: Date.now(), value };
        return value;
      }).finally(() => { if (pending === request) pending = null; });
      pending = request;
      return request.promise;
    },
    create({ label, token, payment_password }) {
      return mutate('/api/credentials', {
        method: 'POST',
        body: { label, token, payment_password },
      });
    },
    setPaymentPassword(credentialId, payment_password, expectedCredentialVersion) {
      return mutate(`${credentialPath(credentialId)}/payment-password`, {
        method: 'PUT',
        body: { payment_password, expected_credential_version: expectedCredentialVersion },
      });
    },
    validate(credentialId, expectedCredentialVersion, expectedRevisionId) {
      return mutate(`${credentialPath(credentialId)}/validate`, {
        method: 'POST',
        body: {
          expected_credential_version: expectedCredentialVersion,
          expected_current_token_revision_id: expectedRevisionId,
        },
      });
    },
    rotateToken(credentialId, token, expectedCredentialVersion, expectedRevisionId) {
      return mutate(`${credentialPath(credentialId)}/rotate-token`, {
        method: 'POST',
        body: {
          token,
          expected_credential_version: expectedCredentialVersion,
          expected_current_token_revision_id: expectedRevisionId,
        },
      });
    },
    update(credentialId, changes) {
      return mutate(credentialPath(credentialId), {
        method: 'PATCH',
        body: changes,
      });
    },
    remove(credentialId, expectedCredentialVersion) {
      return mutate(credentialPath(credentialId), {
        method: 'DELETE',
        body: { expected_credential_version: expectedCredentialVersion },
      });
    },
    executionSettings() {
      return client.request('/api/booking-execution/settings');
    },
    updateExecutionSettings(expectedVersion, settings) {
      return client.request('/api/booking-execution/settings', {
        method: 'PUT',
        body: { expected_version: expectedVersion, settings },
      });
    },
  };
}
