import { describe, expect, it, vi } from 'vitest';

async function loadAdminInvitationApi() {
  const loader = import.meta.glob('./adminInvitations.js')['./adminInvitations.js'];
  const module = loader ? await loader() : null;
  expect(module).not.toBeNull();
  expect(module.createAdminInvitationApi).toBeTypeOf('function');
  return module.createAdminInvitationApi;
}

describe('admin invitation API helper', () => {
  it('requires the existing authenticated HTTP client', async () => {
    const createAdminInvitationApi = await loadAdminInvitationApi();

    expect(() => createAdminInvitationApi()).toThrow(
      'an authenticated HTTP client is required',
    );
  });

  it('creates an invitation without a request body and returns only its code and expiry', async () => {
    const createAdminInvitationApi = await loadAdminInvitationApi();
    const payload = {
      invitation_code: 'synthetic-invitation-code',
      expires_at_utc_ms: 1_800_000_000_000,
    };
    const client = { request: vi.fn().mockResolvedValue(payload) };
    const api = createAdminInvitationApi(client);
    const storageBefore = [
      window.localStorage.length,
      window.sessionStorage.length,
      window.location.href,
    ];

    await expect(api.create()).resolves.toEqual(payload);

    expect(client.request.mock.calls).toEqual([
      ['/api/admin/invitations', { method: 'POST' }],
    ]);
    expect([
      window.localStorage.length,
      window.sessionStorage.length,
      window.location.href,
    ]).toEqual(storageBefore);
  });

  it('rejects a malformed response without echoing the returned code', async () => {
    const createAdminInvitationApi = await loadAdminInvitationApi();
    const code = 'must-not-appear-in-error';
    const client = {
      request: vi.fn().mockResolvedValue({
        invitation_code: code,
        expires_at_utc_ms: Number.MAX_SAFE_INTEGER + 1,
      }),
    };
    const api = createAdminInvitationApi(client);

    let thrown;
    try {
      await api.create();
    } catch (error) {
      thrown = error;
    }

    expect(thrown).toBeInstanceOf(Error);
    expect(thrown.message).not.toContain(code);
  });

  it('does not replay an invitation creation after an uncertain request failure', async () => {
    const createAdminInvitationApi = await loadAdminInvitationApi();
    const client = {
      request: vi.fn().mockRejectedValue(new Error('network unavailable')),
    };
    const api = createAdminInvitationApi(client);

    await expect(api.create()).rejects.toThrow('network unavailable');

    expect(client.request).toHaveBeenCalledTimes(1);
  });
});
