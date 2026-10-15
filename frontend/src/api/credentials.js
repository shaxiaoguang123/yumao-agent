function credentialPath(credentialId) {
  return `/api/credentials/${encodeURIComponent(credentialId)}`;
}

export function createCredentialApi(client) {
  if (typeof client?.request !== 'function') {
    throw new TypeError('an authenticated HTTP client is required');
  }
  return {
    list() {
      return client.request('/api/credentials');
    },
    create({ label, token, payment_password }) {
      return client.request('/api/credentials', {
        method: 'POST',
        body: { label, token, payment_password },
      });
    },
    setPaymentPassword(credentialId, payment_password, expectedCredentialVersion) {
      return client.request(`${credentialPath(credentialId)}/payment-password`, {
        method: 'PUT',
        body: { payment_password, expected_credential_version: expectedCredentialVersion },
      });
    },
    validate(credentialId, expectedCredentialVersion, expectedRevisionId) {
      return client.request(`${credentialPath(credentialId)}/validate`, {
        method: 'POST',
        body: {
          expected_credential_version: expectedCredentialVersion,
          expected_current_token_revision_id: expectedRevisionId,
        },
      });
    },
    rotateToken(credentialId, token, expectedCredentialVersion, expectedRevisionId) {
      return client.request(`${credentialPath(credentialId)}/rotate-token`, {
        method: 'POST',
        body: {
          token,
          expected_credential_version: expectedCredentialVersion,
          expected_current_token_revision_id: expectedRevisionId,
        },
      });
    },
    update(credentialId, changes) {
      return client.request(credentialPath(credentialId), {
        method: 'PATCH',
        body: changes,
      });
    },
    remove(credentialId, expectedCredentialVersion) {
      return client.request(credentialPath(credentialId), {
        method: 'DELETE',
        body: { expected_credential_version: expectedCredentialVersion },
      });
    },
  };
}
