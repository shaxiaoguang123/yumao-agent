import { describe, expect, it, vi } from 'vitest';

async function loadSessionStore() {
  const module = await import('./session.js').catch(() => null);
  expect(module).not.toBeNull();
  expect(module.createSessionStore).toBeTypeOf('function');
  return module.createSessionStore;
}

function makeClient() {
  return { request: vi.fn() };
}

const authenticatedResponse = {
  authenticated: true,
  user: { user_id: 'user-1', username: 'Alice', role: 'user' },
  csrf_token: 'csrf-memory-only',
};

describe('Session store', () => {
  it('exposes a request bridge to the same in-memory authenticated HTTP client', async () => {
    const createSessionStore = await loadSessionStore();
    const client = makeClient();
    const store = createSessionStore({ client });

    await store.request('/api/credentials');

    expect(client.request).toHaveBeenCalledWith('/api/credentials', undefined);
  });

  it('refreshes an authenticated Session into memory', async () => {
    const createSessionStore = await loadSessionStore();
    const client = makeClient();
    client.request.mockResolvedValue(authenticatedResponse);
    const store = createSessionStore({ client });

    await store.refresh();

    expect(client.request).toHaveBeenCalledWith('/api/auth/session');
    expect(store.status).toBe('authenticated');
    expect(store.initialRefreshComplete).toBe(true);
    expect(store.user).toEqual(authenticatedResponse.user);
    expect(store.csrfToken).toBe('csrf-memory-only');
  });

  it('marks a definitive anonymous refresh unauthenticated', async () => {
    const createSessionStore = await loadSessionStore();
    const client = makeClient();
    client.request.mockResolvedValue({ authenticated: false });
    const store = createSessionStore({ client });

    await store.refresh();

    expect(store.status).toBe('unauthenticated');
    expect(store.initialRefreshComplete).toBe(true);
    expect(store.user).toBeNull();
    expect(store.csrfToken).toBe('');
  });

  it('preserves an existing in-memory Session when refresh is temporarily unavailable', async () => {
    const createSessionStore = await loadSessionStore();
    const client = makeClient();
    client.request
      .mockResolvedValueOnce(authenticatedResponse)
      .mockRejectedValueOnce(Object.assign(new Error('offline'), { kind: 'network' }));
    const store = createSessionStore({ client });
    await store.refresh();

    await store.refresh();

    expect(store.status).toBe('unavailable');
    expect(store.initialRefreshComplete).toBe(true);
    expect(store.user).toEqual(authenticatedResponse.user);
    expect(store.csrfToken).toBe('csrf-memory-only');
  });

  it('sets the authenticated state after login and preserves it on invalid credentials', async () => {
    const createSessionStore = await loadSessionStore();
    const client = makeClient();
    client.request
      .mockResolvedValueOnce(authenticatedResponse)
      .mockRejectedValueOnce(Object.assign(new Error('invalid credentials'), {
        status: 401,
        code: 'invalid_credentials',
        sessionInvalid: false,
      }));
    const store = createSessionStore({ client });

    await expect(store.login('Alice', 'strong synthetic password')).resolves.toBe(true);
    await expect(store.login('Alice', 'wrong synthetic password')).resolves.toBe(false);

    expect(client.request).toHaveBeenNthCalledWith(1, '/api/auth/login', {
      method: 'POST',
      body: { username: 'Alice', password: 'strong synthetic password' },
    });
    expect(store.status).toBe('authenticated');
    expect(store.user).toEqual(authenticatedResponse.user);
    expect(store.csrfToken).toBe('csrf-memory-only');
  });

  it('preserves the Session when the current password is wrong', async () => {
    const createSessionStore = await loadSessionStore();
    const { createHttpClient } = await import('../api/http.js');
    const csrf = { value: '' };
    const response = (status, body) => ({
      status,
      ok: status >= 200 && status < 300,
      json: async () => body,
    });
    const fetchImpl = vi.fn()
      .mockResolvedValueOnce(response(200, authenticatedResponse))
      .mockResolvedValueOnce(response(400, { error: 'current_password_invalid' }));
    const client = createHttpClient({
      fetchImpl,
      getCsrfToken: () => csrf.value,
    });
    const store = createSessionStore({ client });
    await store.refresh();
    csrf.value = store.csrfToken;

    await expect(store.changePassword('wrong current password', 'new synthetic password'))
      .resolves.toBe(false);

    expect(store.status).toBe('authenticated');
    expect(store.user).toEqual(authenticatedResponse.user);
    expect(store.csrfToken).toBe('csrf-memory-only');
    expect(store.errorMessage).toBe('当前密码不正确');
    expect(fetchImpl.mock.calls[1][1].headers).toMatchObject({
      'X-CSRF-Token': 'csrf-memory-only',
    });
  });

  it('clears state after confirmed logout success', async () => {
    const createSessionStore = await loadSessionStore();
    const client = makeClient();
    client.request
      .mockResolvedValueOnce(authenticatedResponse)
      .mockResolvedValueOnce(undefined);
    const store = createSessionStore({ client });
    await store.refresh();

    await expect(store.logout()).resolves.toBe(true);

    expect(client.request).toHaveBeenLastCalledWith('/api/auth/logout', { method: 'POST' });
    expect(store.status).toBe('unauthenticated');
    expect(store.user).toBeNull();
    expect(store.csrfToken).toBe('');
    expect(store.logoutUnconfirmed).toBe(false);
  });

  it.each([
    Object.assign(new Error('server error'), { status: 500, kind: 'http' }),
    Object.assign(new Error('network unavailable'), { kind: 'network' }),
    Object.assign(new Error('timed out'), { kind: 'timeout' }),
  ])('keeps state and reports unconfirmed logout on an ambiguous failure', async (error) => {
    const createSessionStore = await loadSessionStore();
    const client = makeClient();
    client.request
      .mockResolvedValueOnce(authenticatedResponse)
      .mockRejectedValueOnce(error);
    const store = createSessionStore({ client });
    await store.refresh();

    await expect(store.logout()).resolves.toBe(false);

    expect(store.status).toBe('authenticated');
    expect(store.user).toEqual(authenticatedResponse.user);
    expect(store.csrfToken).toBe('csrf-memory-only');
    expect(store.logoutUnconfirmed).toBe(true);
    expect(store.logoutMessage).toBe('退出状态未确认，请重试');
  });

  it('clears state when the server explicitly confirms the Session is already invalid', async () => {
    const createSessionStore = await loadSessionStore();
    const client = makeClient();
    client.request
      .mockResolvedValueOnce(authenticatedResponse)
      .mockRejectedValueOnce(Object.assign(new Error('session revoked'), {
        status: 401,
        code: 'session_revoked',
        sessionInvalid: true,
      }));
    const store = createSessionStore({ client });
    await store.refresh();

    await expect(store.logout()).resolves.toBe(true);

    expect(store.status).toBe('unauthenticated');
    expect(store.user).toBeNull();
    expect(store.csrfToken).toBe('');
    expect(store.logoutUnconfirmed).toBe(false);
  });
});
