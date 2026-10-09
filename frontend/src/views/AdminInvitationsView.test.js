import { flushPromises, mount } from '@vue/test-utils';
import { createMemoryHistory, createRouter, RouterView } from 'vue-router';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { reactive } from 'vue';

async function loadView() {
  const loader = import.meta.glob('./AdminInvitationsView.vue')['./AdminInvitationsView.vue'];
  const module = loader ? await loader() : null;
  expect(module).not.toBeNull();
  expect(module.default).toBeTruthy();
  return module.default;
}

function invitationApi(create = vi.fn()) {
  return { create };
}

async function mountView(api, sessionStore = reactive({
  status: 'authenticated',
  user: { user_id: 'synthetic-admin', role: 'admin' },
})) {
  const AdminInvitationsView = await loadView();
  const homeView = { template: '<div />' };
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/', name: 'home', component: homeView },
      { path: '/login', name: 'login', component: homeView },
      {
        path: '/admin/invitations',
        name: 'admin-invitations',
        component: AdminInvitationsView,
      },
    ],
  });
  await router.push('/admin/invitations');
  await router.isReady();
  const wrapper = mount(
    { components: { RouterView }, template: '<RouterView />' },
    {
      global: {
        plugins: [router],
        provide: { adminInvitationApi: api, sessionStore },
      },
    },
  );
  await flushPromises();
  return { wrapper, router, AdminInvitationsView, sessionStore };
}

function submitCreation(wrapper) {
  return wrapper.get('form').trigger('submit');
}

describe('admin invitation management view', () => {
  afterEach(() => {
    vi.restoreAllMocks();
    delete navigator.clipboard;
  });

  it('explains one-time use and the fixed 24-hour lifetime without an expiry selector', async () => {
    const { wrapper } = await mountView(invitationApi());

    expect(wrapper.text()).toContain('24 小时');
    expect(wrapper.text()).toContain('且只能注册一个账户');
    expect(wrapper.find('[data-testid="invitation-expiry-days"]').exists()).toBe(false);
  });

  it('shows a successful invitation once, allows explicit copying, and clears it on dismissal', async () => {
    const code = 'synthetic-one-time-invitation';
    const expiresAt = Date.UTC(2027, 0, 2, 3, 4, 5);
    const create = vi.fn().mockResolvedValue({
      invitation_code: code,
      expires_at_utc_ms: expiresAt,
    });
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, 'clipboard', {
      configurable: true,
      value: { writeText },
    });
    const storageBefore = [
      window.localStorage.length,
      window.sessionStorage.length,
      window.location.href,
    ];
    const { wrapper } = await mountView(invitationApi(create));

    await submitCreation(wrapper);
    await flushPromises();

    expect(create).toHaveBeenCalledOnce();
    expect(wrapper.findAll('[data-testid="invitation-code"]')).toHaveLength(1);
    expect(wrapper.get('[data-testid="invitation-code"]').text()).toBe(code);
    expect(wrapper.get('[data-testid="invitation-expiry"]').attributes('datetime'))
      .toBe(new Date(expiresAt).toISOString());
    expect(wrapper.get('[data-testid="create-invitation"]').element.disabled).toBe(true);

    await wrapper.get('[data-testid="copy-invitation"]').trigger('click');
    await flushPromises();
    expect(writeText).toHaveBeenCalledWith(code);
    expect(wrapper.text()).toContain('已复制');

    await wrapper.get('[data-testid="dismiss-invitation"]').trigger('click');
    await flushPromises();
    expect(wrapper.text()).not.toContain(code);
    expect(wrapper.get('[data-testid="create-invitation"]').element.disabled).toBe(false);
    expect([
      window.localStorage.length,
      window.sessionStorage.length,
      window.location.href,
    ]).toEqual(storageBefore);
  });

  it('reports clipboard failure without exposing or persisting the code', async () => {
    const code = 'synthetic-copy-failure-code';
    const create = vi.fn().mockResolvedValue({
      invitation_code: code,
      expires_at_utc_ms: Date.UTC(2027, 0, 2),
    });
    Object.defineProperty(navigator, 'clipboard', {
      configurable: true,
      value: { writeText: vi.fn().mockRejectedValue(new Error('clipboard unavailable')) },
    });
    const { wrapper } = await mountView(invitationApi(create));

    await submitCreation(wrapper);
    await flushPromises();
    await wrapper.get('[data-testid="copy-invitation"]').trigger('click');
    await flushPromises();

    expect(wrapper.get('[role="status"]').text()).toContain('复制失败');
    expect(wrapper.text()).not.toContain('clipboard unavailable');
    expect(window.localStorage.getItem(code)).toBeNull();
    expect(window.sessionStorage.getItem(code)).toBeNull();
  });

  it('clears invitation text from the mounted page when it unmounts', async () => {
    const code = 'synthetic-unmount-code';
    const create = vi.fn().mockResolvedValue({
      invitation_code: code,
      expires_at_utc_ms: Date.UTC(2027, 0, 2),
    });
    const { wrapper } = await mountView(invitationApi(create));

    await submitCreation(wrapper);
    await flushPromises();
    expect(wrapper.text()).toContain(code);

    wrapper.unmount();

    expect(document.body.textContent).not.toContain(code);
    expect(window.localStorage.getItem(code)).toBeNull();
    expect(window.sessionStorage.getItem(code)).toBeNull();
  });

  it('does not restore invitation state when a pending request resolves after unmount', async () => {
    let resolveCreate;
    const create = vi.fn(() => new Promise((resolve) => { resolveCreate = resolve; }));
    const { wrapper, AdminInvitationsView } = await mountView(invitationApi(create));
    const page = wrapper.findComponent(AdminInvitationsView);
    const setupState = page.vm.$.setupState;

    await submitCreation(wrapper);
    expect(create).toHaveBeenCalledOnce();
    wrapper.unmount();
    expect(setupState.invitationCode).toBe('');
    expect(setupState.expiresAtUtcMs).toBeNull();

    resolveCreate({
      invitation_code: 'synthetic-late-response-code',
      expires_at_utc_ms: Date.UTC(2027, 0, 2),
    });
    await flushPromises();

    expect(setupState.invitationCode).toBe('');
    expect(setupState.expiresAtUtcMs).toBeNull();
  });

  it('ignores a second submission while the first creation request is pending', async () => {
    let resolveCreate;
    const create = vi.fn(() => new Promise((resolve) => { resolveCreate = resolve; }));
    const { wrapper } = await mountView(invitationApi(create));
    const button = wrapper.get('[data-testid="create-invitation"]');

    await wrapper.get('form').trigger('submit');
    await wrapper.get('form').trigger('submit');
    expect(create).toHaveBeenCalledOnce();
    expect(button.element.disabled).toBe(true);

    resolveCreate({
      invitation_code: 'synthetic-pending-code',
      expires_at_utc_ms: Date.UTC(2027, 0, 2),
    });
    await flushPromises();
    expect(wrapper.get('[data-testid="invitation-code"]').text())
      .toBe('synthetic-pending-code');
  });

  it('disables creation after 401 clears the shared Session and guards direct calls', async () => {
    const sessionStore = reactive({ status: 'authenticated', user: { user_id: 'synthetic-admin', role: 'admin' } });
    const create = vi.fn(async () => {
      sessionStore.status = 'unauthenticated';
      sessionStore.user = null;
      throw Object.assign(new Error('synthetic-session-detail'), { status: 401, sessionInvalid: true });
    });
    const { wrapper, AdminInvitationsView } = await mountView(invitationApi(create), sessionStore);
    await submitCreation(wrapper);
    await flushPromises();

    expect(wrapper.get('[data-testid="create-invitation"]').element.disabled).toBe(true);
    expect(wrapper.text()).toContain('登录状态已失效');
    expect(wrapper.get('a[href="/login"]').text()).toContain('重新登录');
    await submitCreation(wrapper);
    await wrapper.findComponent(AdminInvitationsView).vm.$.setupState.createInvitation();
    expect(create).toHaveBeenCalledOnce();
    expect(wrapper.find('[data-testid="invitation-code"]').exists()).toBe(false);
  });

  it('fences late results even if the same administrator signs back in after Session invalidation', async () => {
    let resolveCreate;
    const create = vi.fn(() => new Promise((resolve) => { resolveCreate = resolve; }));
    const { wrapper, sessionStore } = await mountView(invitationApi(create));
    await submitCreation(wrapper);
    sessionStore.status = 'unauthenticated';
    sessionStore.user = null;
    await flushPromises();
    sessionStore.user = { user_id: 'synthetic-admin', role: 'admin' };
    sessionStore.status = 'authenticated';
    resolveCreate({ invitation_code: 'synthetic-late-code', expires_at_utc_ms: Date.UTC(2027, 0, 2) });
    await flushPromises();

    expect(wrapper.find('[data-testid="invitation-code"]').exists()).toBe(false);
    expect(wrapper.text()).not.toContain('synthetic-late-code');
  });

  it('clears displayed plaintext and pending copy feedback when administrator authority is lost', async () => {
    let resolveCopy;
    Object.defineProperty(navigator, 'clipboard', { configurable: true, value: {
      writeText: vi.fn(() => new Promise((resolve) => { resolveCopy = resolve; })),
    } });
    const create = vi.fn().mockResolvedValue({ invitation_code: 'synthetic-revoked-code', expires_at_utc_ms: Date.UTC(2027, 0, 2) });
    const { wrapper, sessionStore } = await mountView(invitationApi(create));
    await submitCreation(wrapper);
    await flushPromises();
    await wrapper.get('[data-testid="copy-invitation"]').trigger('click');
    sessionStore.user.role = 'user';
    await flushPromises();
    resolveCopy();
    await flushPromises();

    expect(wrapper.find('[data-testid="invitation-code"]').exists()).toBe(false);
    expect(wrapper.text()).not.toContain('邀请码已复制');
    expect(wrapper.get('[data-testid="create-invitation"]').element.disabled).toBe(true);
  });

  it.each(['unauthenticated', 'unavailable'])('does not create with Session status %s', async (status) => {
    const create = vi.fn();
    const { wrapper, AdminInvitationsView } = await mountView(invitationApi(create), reactive({ status, user: null }));
    await submitCreation(wrapper);
    await wrapper.findComponent(AdminInvitationsView).vm.$.setupState.createInvitation();
    expect(create).not.toHaveBeenCalled();
    expect(wrapper.get('[data-testid="create-invitation"]').element.disabled).toBe(true);
  });

  it('requires explicit acknowledgement before creating again after an uncertain result', async () => {
    const code = 'synthetic-retry-confirmed-code';
    const create = vi.fn()
      .mockRejectedValueOnce(Object.assign(new Error('network unavailable'), { kind: 'network' }))
      .mockResolvedValueOnce({
        invitation_code: code,
        expires_at_utc_ms: Date.UTC(2027, 0, 2),
      });
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(false);
    const { wrapper } = await mountView(invitationApi(create));

    await submitCreation(wrapper);
    await flushPromises();

    expect(create).toHaveBeenCalledOnce();
    expect(wrapper.get('[data-testid="create-invitation"]').element.disabled).toBe(true);
    expect(wrapper.find('[data-testid="confirm-create-after-uncertain"]').exists()).toBe(true);

    await wrapper.get('form').trigger('submit');
    expect(create).toHaveBeenCalledOnce();

    await wrapper.get('[data-testid="confirm-create-after-uncertain"]').trigger('click');
    expect(confirm).toHaveBeenCalledOnce();
    expect(create).toHaveBeenCalledOnce();

    confirm.mockReturnValue(true);
    await wrapper.get('[data-testid="confirm-create-after-uncertain"]').trigger('click');
    await flushPromises();

    expect(confirm).toHaveBeenCalledTimes(2);
    expect(create).toHaveBeenCalledTimes(2);
    expect(wrapper.get('[data-testid="invitation-code"]').text()).toBe(code);
  });

  it.each([
    [401, 'http', '登录状态已失效'],
    [403, 'http', '管理员权限'],
    [409, 'http', '创建请求发生冲突'],
    [429, 'http', '操作过于频繁'],
    [503, 'http', '创建结果尚未确认'],
    [0, 'invalid_response', '创建结果尚未确认'],
    [0, 'network', '创建结果尚未确认'],
    [0, 'timeout', '创建结果尚未确认'],
  ])('maps status %s / %s to a safe message without retrying', async (status, kind, message) => {
    const secret = 'synthetic-code-that-must-not-be-echoed';
    const create = vi.fn().mockRejectedValue(Object.assign(
      new Error(secret),
      { status, kind },
    ));
    const { wrapper } = await mountView(invitationApi(create));

    await submitCreation(wrapper);
    await flushPromises();

    expect(create).toHaveBeenCalledOnce();
    expect(wrapper.get('[role="alert"]').text()).toContain(message);
    expect(wrapper.text()).not.toContain(secret);
    expect(window.localStorage.getItem(secret)).toBeNull();
    expect(window.sessionStorage.getItem(secret)).toBeNull();
  });
});
