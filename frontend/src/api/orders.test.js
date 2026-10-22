import { describe, expect, it, vi } from 'vitest';
import { createOrderApi, orderErrorMessage } from './orders.js';

it('sends order filters and scoped references in CSRF-protected request bodies', async () => {
  const request = vi.fn(async () => ({}));
  const api = createOrderApi({ request });
  await api.query({ credentialId: 'credential-a', page: 2, status: '5' });
  await api.details({ credentialId: 'credential-a', reference: 'signed-order-reference' });
  expect(request.mock.calls).toEqual([
    ['/api/orders/query', { method: 'POST', body: { credential_id: 'credential-a', page: 2, page_size: 10, status: '5' } }],
    ['/api/orders/details', { method: 'POST', body: { credential_id: 'credential-a', reference: 'signed-order-reference' } }],
  ]);
});

describe('order errors', () => {
  it('has safe messages for expired references, Token failure, and unknown provider text', () => {
    expect(orderErrorMessage({ code: 'order_reference_expired' })).toContain('刷新列表');
    expect(orderErrorMessage({ code: 'credential_token_expired' })).toContain('Token 已过期');
    expect(orderErrorMessage(new Error('private upstream body'))).not.toContain('private');
  });
});
