import { describe, expect, it, vi } from 'vitest';
import { createDiagnosticsApi } from './diagnostics.js';
import { createHttpClient } from './http.js';

describe('diagnostic API boundary', () => {
  it('keeps personal and administrator endpoints distinct and only sends supported filters', async () => {
    const client = { request: vi.fn().mockResolvedValue({}) };
    const api = createDiagnosticsApi(client);
    await api.overview(); await api.system();
    expect(client.request.mock.calls.slice(0, 2).map(call => call[0])).toEqual(['/api/metrics/overview', '/api/admin/metrics']);
    await api.logs({ level: 'warning', module: 'agent', request_id: 'a'.repeat(32), limit: 50, arbitraryPath: '/etc/passwd' });
    const url = new URL(client.request.mock.calls[2][0], 'http://localhost');
    expect(url.searchParams.get('module')).toBe('agent');
    expect(url.searchParams.has('arbitraryPath')).toBe(false);
    await api.detail(12);
    expect(client.request.mock.calls[3][0]).toBe('/api/admin/logs/12');
  });

  it('attaches a bounded request ID to errors while preserving session classification', async () => {
    const onSessionInvalid = vi.fn();
    const client = createHttpClient({ onSessionInvalid, fetchImpl: vi.fn().mockResolvedValue({ ok: false, status: 502,
      headers: { get: () => 'a'.repeat(32) }, json: async () => ({ error: 'provider_timeout' }) }) });
    await expect(client.request('/api/planning/queue-proposals')).rejects.toMatchObject({ code: 'provider_timeout', requestId: 'a'.repeat(32), sessionInvalid: false });
    expect(onSessionInvalid).not.toHaveBeenCalled();
  });
});
