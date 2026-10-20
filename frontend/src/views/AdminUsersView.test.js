import { flushPromises, mount, enableAutoUnmount } from '@vue/test-utils';
import { createMemoryHistory, createRouter, RouterView } from 'vue-router';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { reactive } from 'vue';
import AdminUsersView from './AdminUsersView.vue';

enableAutoUnmount(afterEach);

async function mountView(api) {
  const session = reactive({ status: 'authenticated', user: { user_id: 'admin-1', role: 'admin' } });
  const empty = { template: '<div />' };
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/admin', name: 'admin-users', component: AdminUsersView },
      { path: '/admin/invitations', name: 'admin-invitations', component: empty },
    ],
  });
  await router.push('/admin');
  await router.isReady();
  const wrapper = mount({ components: { RouterView }, template: '<RouterView />' }, {
    global: { plugins: [router], provide: { adminUsersApi: api, sessionStore: session } },
  });
  await flushPromises();
  return { wrapper, session };
}

describe('admin user management', () => {
  afterEach(() => vi.restoreAllMocks());

  it('shows account summaries and safe user fields, and revokes access on disable', async () => {
    const admin = { user_id: 'admin-1', username: 'admin', role: 'admin', status: 'active', created_at_utc_ms: 1_700_000_000_000 };
    const alice = { user_id: 'user-1', username: 'Alice', role: 'user', status: 'active', created_at_utc_ms: 1_700_000_000_000, token: 'secret-token-value', api_key: 'secret-api-key', password: 'secret-password' };
    const result = (target) => ({
      users: [admin, target], total: 2, limit: 50, offset: 0,
      summary: { total: 2, active: target.status === 'active' ? 2 : 1, disabled: target.status === 'disabled' ? 1 : 0, admins: 1, active_admins: 1 },
    });
    const api = {
      list: vi.fn().mockResolvedValueOnce(result(alice)).mockResolvedValue(result({ ...alice, status: 'disabled' })),
      disable: vi.fn().mockResolvedValue(undefined),
      enable: vi.fn().mockResolvedValue(undefined),
    };
    vi.spyOn(window, 'confirm').mockReturnValue(true);
    const { wrapper } = await mountView(api);

    expect(wrapper.get('[aria-label="用户统计"]').text()).toContain('2');
    expect(wrapper.text()).toContain('Alice');
    expect(wrapper.text()).not.toContain('secret-token-value');
    expect(wrapper.text()).not.toContain('secret-api-key');
    expect(wrapper.text()).not.toContain('secret-password');
    const adminRow = wrapper.findAll('tbody tr').find((row) => row.text().includes('当前账户'));
    expect(adminRow.get('button').element.disabled).toBe(true);

    const aliceRow = wrapper.findAll('tbody tr').find((row) => row.text().includes('Alice'));
    await aliceRow.get('button').trigger('click');
    await flushPromises();
    expect(api.disable).toHaveBeenCalledWith('user-1');
    expect(wrapper.text()).toContain('Alice 已停用');
    expect(wrapper.text()).toContain('已停用');
  });
});
