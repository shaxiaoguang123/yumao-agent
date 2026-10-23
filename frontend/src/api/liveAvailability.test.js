import { describe, expect, it, vi } from 'vitest';
import { createLiveAvailabilityApi } from './liveAvailability.js';
describe('read-only availability API', () => {
  it('sends semantic dates and opaque references through authenticated requests', async () => {
    const client = { request: vi.fn(async () => ({})) };
    const api = createLiveAvailabilityApi(client);
    await api.options(); await api.categories('owned-credential');
    await api.grid({ credentialId: 'owned-credential', scopeReference: 'opaque-ref', targetDate: '2026-10-15' });
    expect(client.request.mock.calls).toEqual([
      ['/api/availability/live/options'],
      ['/api/availability/live/categories', { timeoutMs: 15_000, method: 'POST', body: { credential_id: 'owned-credential' } }],
      ['/api/availability/live/grid', { timeoutMs: 15_000, method: 'POST', body: { credential_id: 'owned-credential', scope_reference: 'opaque-ref', target_date: '2026-10-15' } }],
    ]);
  });
});
