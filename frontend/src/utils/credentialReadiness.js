export function planSetupRequirement(credentials) {
  if (!Array.isArray(credentials) || credentials.length === 0) return 'token';

  const tokenReady = credentials.filter((credential) => (
    credential?.enabled === true
    && credential.account_binding_state === 'confirmed'
    && credential.requires_revalidation === false
    && credential.last_confirmed_validation_state === 'confirmed_valid'
    && credential.expiry_state !== 'expired'
  ));

  if (!tokenReady.length) return 'token';
  if (!tokenReady.some((credential) => credential.has_payment_password === true)) {
    return 'payment_password';
  }
  return '';
}
