import { describe, expect, it, vi } from 'vitest';
import { createAdminUsersApi } from './adminUsers.js';

describe('admin users API', () => {
  it('requests filtered pages and encodes user identifiers for status actions', async () => {
    const request = vi.fn(async () => ({}));
    const api = createAdminUsersApi({ request });

    await api.list({ q: 'A B', role: 'user', status: 'disabled', limit: 25, offset: 50 });
    await api.disable('user/id');
    await api.enable('user/id');

    expect(request).toHaveBeenNthCalledWith(1, '/api/admin/users?role=user&status=disabled&limit=25&offset=50&q=A+B');
    expect(request).toHaveBeenNthCalledWith(2, '/api/admin/users/user%2Fid/disable', { method: 'POST', body: {} });
    expect(request).toHaveBeenNthCalledWith(3, '/api/admin/users/user%2Fid/enable', { method: 'POST', body: {} });
  });
});
