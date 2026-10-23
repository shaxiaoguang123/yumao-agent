import { describe, expect, it, vi } from 'vitest';
import { createHttpClient } from './http.js';
import { createSessionStore } from '../stores/session.js';

async function loadCredentialApi() {
  const loader = import.meta.glob('./credentials.js')['./credentials.js'];
  const module = loader ? await loader() : null;
  expect(module).not.toBeNull();
  expect(module.createCredentialApi).toBeTypeOf('function');
  return module.createCredentialApi;
}

describe('Credential API helpers', () => {
  it('prefers an in-flight fresh check to a cached snapshot and discards the snapshot on failure', async () => {
    const createCredentialApi=await loadCredentialApi();let fail;
    const client={request:vi.fn().mockResolvedValueOnce({credentials:[]}).mockImplementationOnce(()=>new Promise((_,reject)=>{fail=reject;})).mockResolvedValue({credentials:[]})};
    const api=createCredentialApi(client);await api.list();const fresh=api.list();
    expect(api.list({reuse:true})).toBe(fresh);
    const failure=expect(fresh).rejects.toThrow('synthetic');fail(new Error('synthetic'));await failure;
    await api.list({reuse:true});expect(client.request).toHaveBeenCalledTimes(3);
  });
  it('does not repopulate the snapshot from a read that started before a mutation', async () => {
    const createCredentialApi=await loadCredentialApi();let finish;
    const client={request:vi.fn().mockImplementationOnce(()=>new Promise(resolve=>{finish=resolve;})).mockResolvedValue({credentials:[]})};
    const api=createCredentialApi(client),old=api.list();
    await api.update('owned',{enabled:false});finish({credentials:[{credential_id:'stale'}]});await old;
    const fresh=await api.list({reuse:true});expect(fresh.credentials).toEqual([]);expect(client.request).toHaveBeenCalledTimes(3);
  });
  it('coalesces owner reads, reuses only a recent UI snapshot and refreshes after mutations', async () => {
    const createCredentialApi = await loadCredentialApi();
    const client={user:{user_id:'owner-a'},csrfToken:'csrf-a',invalidationEpoch:0,request:vi.fn(async()=>({credentials:[]}))};
    const api=createCredentialApi(client);
    await Promise.all([api.list(),api.list()]);expect(client.request).toHaveBeenCalledOnce();
    await api.list({reuse:true});expect(client.request).toHaveBeenCalledOnce();
    await api.list();expect(client.request).toHaveBeenCalledTimes(2);
    client.user={user_id:'owner-b'};await api.list({reuse:true});expect(client.request).toHaveBeenCalledTimes(3);
    client.invalidationEpoch++;await api.list({reuse:true});expect(client.request).toHaveBeenCalledTimes(4);
    await api.update('owned', {enabled:false});await api.list({reuse:true});expect(client.request).toHaveBeenCalledTimes(6);
  });
  it('requires a configured HTTP client instead of a global client without Session CSRF', async () => {
    const createCredentialApi = await loadCredentialApi();

    expect(() => createCredentialApi()).toThrow('an authenticated HTTP client is required');
  });

  it('uses the existing HTTP client for all owner-scoped operations', async () => {
    const createCredentialApi = await loadCredentialApi();
    const client = { request: vi.fn().mockResolvedValue({ ok: true }) };
    const api = createCredentialApi(client);
    const token = 'synthetic-secret-token';

    await api.list();
    await api.create({ label: 'Primary', token, payment_password: 'synthetic-payment-password' });
    await api.setPaymentPassword('credential-a', 'replacement-payment-password', 3);
    await api.validate('credential-a', 3, 'revision-a');
    await api.rotateToken('credential-a', token, 3, 'revision-a');
    await api.update('credential-a', { expected_credential_version: 3, enabled: false });
    await api.update('credential-a', { expected_credential_version: 4, enabled: true });
    await api.remove('credential-a', 4);
    await api.executionSettings();
    await api.updateExecutionSettings(0, { reconciliation_time: '00:30' });

    expect(client.request.mock.calls).toEqual([
      ['/api/credentials'],
      ['/api/credentials', { method: 'POST', body: { label: 'Primary', token, payment_password: 'synthetic-payment-password' } }],
      ['/api/credentials/credential-a/payment-password', { method: 'PUT', body: { payment_password: 'replacement-payment-password', expected_credential_version: 3 } }],
      ['/api/credentials/credential-a/validate', {
        method: 'POST',
        body: {
          expected_credential_version: 3,
          expected_current_token_revision_id: 'revision-a',
        },
      }],
      ['/api/credentials/credential-a/rotate-token', {
        method: 'POST',
        body: {
          token,
          expected_credential_version: 3,
          expected_current_token_revision_id: 'revision-a',
        },
      }],
      ['/api/credentials/credential-a', {
        method: 'PATCH',
        body: { expected_credential_version: 3, enabled: false },
      }],
      ['/api/credentials/credential-a', {
        method: 'PATCH',
        body: { expected_credential_version: 4, enabled: true },
      }],
      ['/api/credentials/credential-a', {
        method: 'DELETE',
        body: { expected_credential_version: 4 },
      }],
      ['/api/booking-execution/settings'],
      ['/api/booking-execution/settings', {
        method: 'PUT',
        body: { expected_version: 0, settings: { reconciliation_time: '00:30' } },
      }],
    ]);
    expect(window.localStorage.getItem(token)).toBeNull();
    expect(window.sessionStorage.getItem(token)).toBeNull();
    expect(window.location.search).toBe('');
  });

  it('inherits credentials and in-memory CSRF behavior from the shared HTTP client', async () => {
    const createCredentialApi = await loadCredentialApi();
    const fetchImpl = vi.fn().mockResolvedValue({
      ok: true,
      status: 201,
      json: async () => ({ credential: { credential_id: 'credential-a' } }),
    });
    const client = createHttpClient({ fetchImpl, getCsrfToken: () => 'csrf-memory-only' });
    const api = createCredentialApi(client);

    await api.create({ label: 'Primary', token: 'synthetic-token', payment_password: 'synthetic-payment-password' });

    expect(fetchImpl).toHaveBeenCalledWith('/api/credentials', expect.objectContaining({
      method: 'POST',
      credentials: 'include',
      headers: expect.objectContaining({ 'X-CSRF-Token': 'csrf-memory-only' }),
    }));
  });

  it('uses the SessionStore request bridge so mutations receive the current CSRF token', async () => {
    const createCredentialApi = await loadCredentialApi();
    const fetchImpl = vi.fn().mockResolvedValue({
      ok: true,
      status: 201,
      json: async () => ({ credential: { credential_id: 'credential-a' } }),
    });
    let sessionStore;
    const client = createHttpClient({
      fetchImpl,
      getCsrfToken: () => sessionStore?.csrfToken || '',
    });
    sessionStore = createSessionStore({ client });
    sessionStore.csrfToken = 'csrf-from-session-memory';
    const api = createCredentialApi(sessionStore);

    await api.create({ label: 'Primary', token: 'synthetic-token', payment_password: 'synthetic-payment-password' });

    expect(fetchImpl.mock.calls[0][1]).toMatchObject({
      credentials: 'include',
      headers: { 'X-CSRF-Token': 'csrf-from-session-memory' },
    });
  });
});
