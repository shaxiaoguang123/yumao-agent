// All data in this suite is synthetic; no upstream protocol fixtures.
const SYNTHETIC_CSRF = 'VISUAL-QA-SYNTHETIC-CSRF-NOT-A-SECRET';
const SYNTHETIC_CODE = 'VISUAL-QA-SYNTHETIC-INVITATION-NOT-VALID';
const SYNTHETIC_PASSWORD = 'Visual-QA-only-passphrase-1234';
const SYNTHETIC_TOKEN = 'VISUAL-QA-SYNTHETIC-TOKEN-NOT-VALID';
const clone = (value) => JSON.parse(JSON.stringify(value));
const credential = (id, label, extra = {}) => ({
  credential_id: id, label, credential_version: 3, current_token_revision_id: `${id}-synthetic-revision`, enabled: true,
  account_binding_state: 'confirmed', expiry_state: 'expiry_ok', last_confirmed_validation_state: 'confirmed_valid', requires_revalidation: false,
  token_expires_at_utc: '2026-12-31T12:00:00Z', last_successful_validation_at_utc: '2026-10-09T08:00:00Z',
  latest_requested_validation_attempt: { operation_kind: 'validate_current', attempt_result: 'success', started_at_utc: '2026-10-09T08:00:00Z', completed_at_utc: '2026-10-09T08:00:01Z' }, ...extra,
});
const fixtures = [
  credential('visual-confirmed', '合成凭据 · 已确认'),
  credential('visual-expired', '合成凭据 · 已过期', { expiry_state: 'expired', token_expires_at_utc: '2026-01-01T00:00:00Z' }),
  credential('visual-unresolved', '合成凭据 · 身份待确认', { account_binding_state: 'unresolved' }),
  credential('visual-reconfirmation', '合成凭据 · 需重新确认', { account_binding_state: 'needs_reconfirmation', latest_requested_validation_attempt: { operation_kind: 'validate_current', attempt_result: 'rate_limited', started_at_utc: '2026-10-09T09:00:00Z', completed_at_utc: '2026-10-09T09:00:01Z' } }),
  credential('visual-disabled', '合成凭据 · 已停用', { enabled: false, expiry_state: 'expiring_soon', requires_revalidation: true }),
];
const viewports = [
  { name: 'desktop', width: 1440, height: 900 }, { name: 'tablet', width: 768, height: 1024 },
  { name: 'phone', width: 390, height: 844 }, { name: 'narrow-phone', width: 320, height: 700 },
];

export { SYNTHETIC_CSRF, SYNTHETIC_CODE, SYNTHETIC_PASSWORD, SYNTHETIC_TOKEN, clone, credential, fixtures, viewports };
