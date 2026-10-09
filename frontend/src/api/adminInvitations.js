export function createAdminInvitationApi(client) {
  if (typeof client?.request !== 'function') {
    throw new TypeError('an authenticated HTTP client is required');
  }

  return {
    async create() {
      const payload = await client.request('/api/admin/invitations', {
        method: 'POST',
      });
      if (
        !payload
        || typeof payload.invitation_code !== 'string'
        || payload.invitation_code.length === 0
        || payload.invitation_code.trim() !== payload.invitation_code
        || !Number.isSafeInteger(payload.expires_at_utc_ms)
        || payload.expires_at_utc_ms <= 0
      ) {
        const error = new Error('invalid_invitation_response');
        error.kind = 'invalid_response';
        throw error;
      }

      return {
        invitation_code: payload.invitation_code,
        expires_at_utc_ms: payload.expires_at_utc_ms,
      };
    },
  };
}
