import { describe, expect, it, vi } from 'vitest';

async function loadHttpClient() {
  const module = await import('./http.js').catch(() => null);
  expect(module).not.toBeNull();
  expect(module.createHttpClient).toBeTypeOf('function');
  return module.createHttpClient;
}

function response(status, body = {}) {
  return {
    status,
    ok: status >= 200 && status < 300,
    json: async () => body,
  };
}

describe('HTTP helper', () => {
  it('sends credentials on GET and ordinary requests', async () => {
    const createHttpClient = await loadHttpClient();
    const fetchImpl = vi.fn()
      .mockResolvedValueOnce(response(200, { authenticated: false }))
      .mockResolvedValueOnce(response(201, { user_id: 'user-1' }));
    const client = createHttpClient({ fetchImpl });

    await client.request('/api/auth/session');
    await client.request('/api/auth/register', {
      method: 'POST',
      body: { invitation_code: 'synthetic-invite' },
    });

    expect(fetchImpl).toHaveBeenNthCalledWith(
      1,
      '/api/auth/session',
      expect.objectContaining({ credentials: 'include', method: 'GET' }),
    );
    expect(fetchImpl).toHaveBeenNthCalledWith(
      2,
      '/api/auth/register',
      expect.objectContaining({ credentials: 'include', method: 'POST' }),
    );
  });

  it('attaches the in-memory CSRF token to protected mutations', async () => {
    const createHttpClient = await loadHttpClient();
    const fetchImpl = vi.fn().mockResolvedValue(response(204));
    const client = createHttpClient({ fetchImpl, getCsrfToken: () => 'csrf-in-memory' });

    await client.request('/api/auth/logout', { method: 'POST' });

    expect(fetchImpl.mock.calls[0][1].headers).toMatchObject({
      'X-CSRF-Token': 'csrf-in-memory',
    });
  });

  it('clears auth on a protected-route 401', async () => {
    const createHttpClient = await loadHttpClient();
    const onSessionInvalid = vi.fn();
    const client = createHttpClient({
      fetchImpl: vi.fn().mockResolvedValue(response(401, { error: 'session_invalid' })),
      onSessionInvalid,
    });

    await expect(client.request('/api/auth/session')).rejects.toMatchObject({
      status: 401,
      sessionInvalid: true,
    });
    expect(onSessionInvalid).toHaveBeenCalledOnce();
  });

  it('clears auth on a protected-route 401 even without a response error code', async () => {
    const createHttpClient = await loadHttpClient();
    const onSessionInvalid = vi.fn();
    const client = createHttpClient({
      fetchImpl: vi.fn().mockResolvedValue(response(401, {})),
      onSessionInvalid,
    });

    await expect(client.request('/api/auth/session')).rejects.toMatchObject({
      status: 401,
      sessionInvalid: true,
    });
    expect(onSessionInvalid).toHaveBeenCalledOnce();
  });

  it.each([
    [403, { error: 'csrf_invalid' }],
    [429, { error: 'rate_limited' }],
    [500, { error: 'server_error' }],
  ])('preserves auth after HTTP %s', async (status, body) => {
    const createHttpClient = await loadHttpClient();
    const onSessionInvalid = vi.fn();
    const client = createHttpClient({
      fetchImpl: vi.fn().mockResolvedValue(response(status, body)),
      onSessionInvalid,
    });

    await expect(client.request('/api/auth/session')).rejects.toMatchObject({ status });
    expect(onSessionInvalid).not.toHaveBeenCalled();
  });

  it('does not treat invalid login credentials as an expired Session', async () => {
    const createHttpClient = await loadHttpClient();
    const onSessionInvalid = vi.fn();
    const client = createHttpClient({
      fetchImpl: vi.fn().mockResolvedValue(response(401, { error: 'invalid_credentials' })),
      onSessionInvalid,
    });

    await expect(client.request('/api/auth/login', { method: 'POST' })).rejects.toMatchObject({
      status: 401,
      sessionInvalid: false,
    });
    expect(onSessionInvalid).not.toHaveBeenCalled();
  });

  it('classifies network and timeout failures without clearing auth', async () => {
    const createHttpClient = await loadHttpClient();
    const onSessionInvalid = vi.fn();
    const fetchImpl = vi.fn()
      .mockRejectedValueOnce(new TypeError('network unavailable'))
      .mockRejectedValueOnce(new DOMException('request timed out', 'TimeoutError'));
    const client = createHttpClient({ fetchImpl, onSessionInvalid });

    await expect(client.request('/api/auth/session')).rejects.toMatchObject({ kind: 'network' });
    await expect(client.request('/api/auth/session')).rejects.toMatchObject({ kind: 'timeout' });
    expect(onSessionInvalid).not.toHaveBeenCalled();
  });

  it('recognizes an explicit invalid-session response for logout reconciliation', async () => {
    const createHttpClient = await loadHttpClient();
    const onSessionInvalid = vi.fn();
    const client = createHttpClient({
      fetchImpl: vi.fn().mockResolvedValue(response(401, { error: 'session_revoked' })),
      onSessionInvalid,
    });

    await expect(client.request('/api/auth/logout', { method: 'POST' })).rejects.toMatchObject({
      sessionInvalid: true,
    });
    expect(onSessionInvalid).toHaveBeenCalledOnce();
  });
});
