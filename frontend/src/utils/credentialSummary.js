// Calendar expiry, validation and account binding stay independent facts.
export function needsAttention(credential) {
 return credential.expiry_state === 'expired' || credential.expiry_state === 'expiring_soon'
  || credential.last_confirmed_validation_state === 'confirmed_invalid'
  || credential.account_binding_state === 'unresolved' || credential.account_binding_state === 'needs_reconfirmation'
  || Boolean(credential.requires_revalidation);
}
