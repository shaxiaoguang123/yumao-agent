import { describe, expect, it } from 'vitest';
import { planSetupRequirement } from './credentialReadiness.js';

const ready = (overrides = {}) => ({
  enabled: true,
  account_binding_state: 'confirmed',
  requires_revalidation: false,
  last_confirmed_validation_state: 'confirmed_valid',
  expiry_state: 'valid',
  has_payment_password: true,
  ...overrides,
});

describe('plan setup requirement', () => {
  it('requires a Token when the list is missing or empty', () => {
    expect(planSetupRequirement()).toBe('token');
    expect(planSetupRequirement([])).toBe('token');
  });

  it('requires a valid Token before checking its payment password', () => {
    expect(planSetupRequirement([ready({ last_confirmed_validation_state: 'confirmed_invalid' })]))
      .toBe('token');
    expect(planSetupRequirement([ready({ has_payment_password: false })]))
      .toBe('payment_password');
  });

  it('passes when any enabled, valid credential has a payment password', () => {
    expect(planSetupRequirement([
      ready({ enabled: false }),
      ready({ has_payment_password: false }),
      ready(),
    ])).toBe('');
  });
});
