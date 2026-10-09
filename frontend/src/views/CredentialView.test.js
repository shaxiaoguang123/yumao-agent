import { flushPromises, mount } from '@vue/test-utils';
import { createMemoryHistory, createRouter, RouterView } from 'vue-router';
import { describe, expect, it, vi } from 'vitest';
import { nextTick, reactive } from 'vue';

const credential = (overrides = {}) => ({
  credential_id: 'credential-a',
  label: '主用凭据',
  credential_version: 3,
  current_token_revision_id: 'revision-a',
  enabled: true,
  account_binding_state: 'confirmed',
  requires_revalidation: false,
  expiry_state: 'expiring_soon',
  token_expires_at_utc: '2026-10-15T12:00:00.000Z',
  last_confirmed_validation_state: 'confirmed_valid',
  last_successful_validation_at_utc: '2026-10-08T10:00:00.000Z',
  latest_requested_validation_attempt: {
    validation_attempt_id: 9,
    operation_kind: 'validate_current',
    current_token_revision_snapshot_id: 'revision-a',
    token_revision_id: 'revision-a',
    started_at_utc: '2026-10-08T10:01:00.000Z',
    completed_at_utc: '2026-10-08T10:01:02.000Z',
    attempt_result: 'rate_limited',
    account_binding_outcome: 'not_checked',
    apply_state: 'not_dispatched',
  },
  ...overrides,
});

async function loadView() {
  const loader = import.meta.glob('./CredentialView.vue')['./CredentialView.vue'];
  const module = loader ? await loader() : null;
  expect(module).not.toBeNull();
  expect(module.default).toBeTruthy();
  return module.default;
}

async function loadHomeView() {
  const module = await import('./HomeView.vue');
  expect(module.default).toBeTruthy();
  return module.default;
}

async function loadApp() {
  const module = await import('../App.vue');
  expect(module.default).toBeTruthy();
  return module.default;
}

function makeApi({ credentials = [], ...overrides } = {}) {
  return {
    list: vi.fn().mockResolvedValue({ credentials }),
    create: vi.fn().mockResolvedValue({ credential: credential() }),
    validate: vi.fn().mockResolvedValue({ result: 'validated', credential: credential() }),
    rotateToken: vi.fn().mockResolvedValue({ result: 'token_rotated', credential: credential() }),
    update: vi.fn().mockResolvedValue({ result: 'credential_updated', credential: credential() }),
    remove: vi.fn().mockResolvedValue(undefined),
    ...overrides,
  };
}

async function mountView(api) {
  const CredentialView = await loadView();
  const EmptyView = { template: '<div />' };
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/credentials', name: 'credentials', component: CredentialView },
      { path: '/elsewhere', name: 'elsewhere', component: EmptyView },
    ],
  });
  await router.push('/credentials');
  await router.isReady();
  const wrapper = mount({ components: { RouterView }, template: '<RouterView />' }, {
    global: { plugins: [router], provide: { credentialApi: api } },
  });
  await flushPromises();
  return { wrapper, router };
}

describe('Credential management view', () => {
  it.each(['upstream_unavailable', 'network'])('does not claim an empty list after initial %s failure; retries to a genuine empty state', async (code) => {
    const list = vi.fn().mockRejectedValueOnce(Object.assign(new Error('synthetic-error'), { code }))
      .mockResolvedValueOnce({ credentials: [] });
    const { wrapper } = await mountView(makeApi({ list }));
    expect(wrapper.get('[role="alert"]').exists()).toBe(true);
    expect(wrapper.text()).not.toContain('暂无预约凭据');
    await wrapper.get('[role="alert"] button').trigger('click');
    await flushPromises();
    expect(list).toHaveBeenCalledTimes(2);
    expect(wrapper.find('[role="alert"]').exists()).toBe(false);
    expect(wrapper.text()).toContain('暂无预约凭据');
  });

  it('does not present a previous list as freshly loaded after refresh fails', async () => {
    const list = vi.fn().mockResolvedValueOnce({ credentials: [credential()] })
      .mockRejectedValueOnce(Object.assign(new Error('synthetic-error'), { code: 'upstream_unavailable' }));
    const { wrapper } = await mountView(makeApi({ list }));
    expect(wrapper.find('[data-testid="credential-card-credential-a"]').exists()).toBe(true);
    await wrapper.get('.section-heading button').trigger('click');
    await flushPromises();
    expect(wrapper.get('[role="alert"]').exists()).toBe(true);
    expect(wrapper.find('[data-testid="credential-card-credential-a"]').exists()).toBe(false);
    expect(wrapper.text()).not.toContain('暂无预约凭据');
  });

  it('reports a failed refresh after a mutation instead of silently showing stale data', async () => {
    const list = vi.fn().mockResolvedValueOnce({ credentials: [credential()] })
      .mockRejectedValueOnce(Object.assign(new Error('synthetic-error'), { code: 'upstream_unavailable' }));
    const { wrapper } = await mountView(makeApi({ list }));
    await wrapper.get('[data-testid="validate-credential-a"]').trigger('click');
    await flushPromises();
    expect(wrapper.get('[role="alert"]').exists()).toBe(true);
    expect(wrapper.find('[data-testid="credential-card-credential-a"]').exists()).toBe(false);
  });

  it('shows expiry, Token validity, account binding, latest request and last success separately', async () => {
    const api = makeApi({ credentials: [credential()] });
    const { wrapper } = await mountView(api);

    expect(wrapper.text()).toContain('即将过期');
    expect(wrapper.text()).toContain('Token 验证已验证有效');
    expect(wrapper.text()).toContain('账户连续性已确认');
    expect(wrapper.text()).toContain('最近发起的验证');
    expect(wrapper.text()).toContain('受到限流');
    expect(wrapper.text()).toContain('最近成功验证');
    expect(wrapper.text()).toContain('2026年10月8日');
  });

  it('explains unresolved and reconfirmation states and hides rotation controls', async () => {
    const api = makeApi({
      credentials: [
        credential({ credential_id: 'unresolved', account_binding_state: 'unresolved' }),
        credential({ credential_id: 'reconfirm', account_binding_state: 'needs_reconfirmation' }),
      ],
    });
    const { wrapper } = await mountView(api);

    expect(wrapper.text()).toContain('账户连续性尚未确认');
    expect(wrapper.text()).toContain('账户连续性需要重新确认');
    expect(wrapper.find('[data-testid="rotate-unresolved"]').exists()).toBe(false);
    expect(wrapper.find('[data-testid="rotate-reconfirm"]').exists()).toBe(false);
  });

  it('creates a Credential and clears the in-memory Token field after success', async () => {
    const token = 'synthetic-token-do-not-store';
    const api = makeApi({
      credentials: [],
      create: vi.fn().mockResolvedValue({ credential: credential() }),
      list: vi.fn()
        .mockResolvedValueOnce({ credentials: [] })
        .mockResolvedValueOnce({ credentials: [credential()] }),
    });
    const { wrapper, router } = await mountView(api);
    const storageBefore = window.localStorage.length + window.sessionStorage.length;
    await wrapper.get('[data-testid="credential-label"]').setValue('Primary');
    await wrapper.get('[data-testid="credential-token"]').setValue(token);
    await wrapper.get('[data-testid="credential-create"]').trigger('submit');
    await flushPromises();

    expect(api.create).toHaveBeenCalledWith({ label: 'Primary', token });
    expect(wrapper.get('[data-testid="credential-token"]').element.value).toBe('');
    expect(window.localStorage.length + window.sessionStorage.length).toBe(storageBefore);
    expect(router.currentRoute.value.fullPath).not.toContain(token);
  });

  it('shows initial loading state while the owner-scoped list is pending', async () => {
    const CredentialView = await loadView();
    let resolveList;
    const api = makeApi({
      list: vi.fn(() => new Promise((resolve) => { resolveList = resolve; })),
    });
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [{ path: '/credentials', name: 'credentials', component: CredentialView }],
    });
    await router.push('/credentials');
    const wrapper = mount({ components: { RouterView }, template: '<RouterView />' }, {
      global: { plugins: [router], provide: { credentialApi: api } },
    });
    await nextTick();

    expect(wrapper.text()).toContain('正在读取凭据状态');
    resolveList({ credentials: [] });
    await flushPromises();
    expect(wrapper.text()).toContain('暂无预约凭据');
  });

  it('disables the create action while a request is in flight', async () => {
    let resolveCreate;
    const api = makeApi({
      credentials: [],
      create: vi.fn(() => new Promise((resolve) => { resolveCreate = resolve; })),
    });
    const { wrapper } = await mountView(api);
    await wrapper.get('[data-testid="credential-label"]').setValue('Primary');
    await wrapper.get('[data-testid="credential-token"]').setValue('synthetic-busy-token');
    await wrapper.get('[data-testid="credential-create"]').trigger('submit');
    await nextTick();

    expect(wrapper.get('[data-testid="credential-create"] button[type="submit"]').element.disabled).toBe(true);
    expect(wrapper.get('[data-testid="credential-create"]').text()).toContain('验证并保存中');
    resolveCreate({ credential: credential() });
    await flushPromises();
    expect(wrapper.get('[data-testid="credential-token"]').element.value).toBe('');
  });

  it('clears the create Token field after failure and displays only a safe message', async () => {
    const token = 'synthetic-token-on-failure';
    const api = makeApi({
      credentials: [],
      create: vi.fn().mockRejectedValue(Object.assign(new Error('raw message'), {
        code: 'upstream_validation_unknown',
      })),
    });
    const { wrapper } = await mountView(api);
    await wrapper.get('[data-testid="credential-label"]').setValue('Primary');
    await wrapper.get('[data-testid="credential-token"]').setValue(token);
    await wrapper.get('[data-testid="credential-create"]').trigger('submit');
    await flushPromises();

    expect(wrapper.get('[data-testid="credential-token"]').element.value).toBe('');
    expect(wrapper.get('[role="alert"]').text()).toContain('上游验证暂不可用');
    expect(wrapper.text()).not.toContain(token);
    expect(wrapper.text()).not.toContain('raw message');
  });

  it('clears the create form when the user cancels', async () => {
    const api = makeApi({ credentials: [] });
    const { wrapper } = await mountView(api);
    await wrapper.get('[data-testid="credential-label"]').setValue('Draft');
    await wrapper.get('[data-testid="credential-token"]').setValue('synthetic-cancelled-token');

    await wrapper.get('[data-testid="credential-create-cancel"]').trigger('click');

    expect(wrapper.get('[data-testid="credential-label"]').element.value).toBe('');
    expect(wrapper.get('[data-testid="credential-token"]').element.value).toBe('');
    expect(api.create).not.toHaveBeenCalled();
  });

  it('validates with the current version and revision', async () => {
    const api = makeApi({ credentials: [credential()] });
    const { wrapper } = await mountView(api);
    await wrapper.get('[data-testid="validate-credential-a"]').trigger('click');
    await flushPromises();

    expect(api.validate).toHaveBeenCalledWith('credential-a', 3, 'revision-a');
  });

  it('re-enables a disabled Credential and leaves revalidation as a separate state', async () => {
    const disabled = credential({ enabled: false, requires_revalidation: true });
    const api = makeApi({ credentials: [disabled] });
    const { wrapper } = await mountView(api);

    await wrapper.get('[data-testid="credential-enable-credential-a"]').trigger('click');
    await flushPromises();

    expect(api.update).toHaveBeenCalledWith('credential-a', {
      expected_credential_version: 3,
      enabled: true,
    });
    expect(wrapper.get('[data-testid="credential-card-credential-a"]').text()).toContain('需要再次验证当前 Token');
  });

  it('requires confirmation before deleting a Credential and honors cancellation', async () => {
    const api = makeApi({ credentials: [credential()] });
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(false);
    const { wrapper } = await mountView(api);

    await wrapper.get('[data-testid="credential-delete-credential-a"]').trigger('click');
    await flushPromises();

    expect(confirm).toHaveBeenCalledOnce();
    expect(confirm).toHaveBeenCalledWith(expect.stringContaining('删除'));
    expect(api.remove).not.toHaveBeenCalled();
    expect(wrapper.text()).not.toContain('凭据已删除');
  });

  it('rotates only a confirmed Credential and clears the Token field on cancel or failure', async () => {
    const api = makeApi({
      credentials: [credential()],
      rotateToken: vi.fn().mockRejectedValue(Object.assign(new Error('raw message'), {
        code: 'credential_account_mismatch',
      })),
    });
    const { wrapper } = await mountView(api);
    await wrapper.get('[data-testid="rotate-credential-a"]').trigger('click');
    const tokenInput = wrapper.get('[data-testid="rotation-token"]');
    await tokenInput.setValue('synthetic-rotation-token');
    await wrapper.get('[data-testid="rotation-cancel"]').trigger('click');
    expect(wrapper.find('[data-testid="rotation-token"]').exists()).toBe(false);

    await wrapper.get('[data-testid="rotate-credential-a"]').trigger('click');
    await wrapper.get('[data-testid="rotation-token"]').setValue('synthetic-rotation-token');
    await wrapper.get('[data-testid="rotation-submit"]').trigger('submit');
    await flushPromises();

    expect(api.rotateToken).toHaveBeenCalledWith('credential-a', 'synthetic-rotation-token', 3, 'revision-a');
    expect(wrapper.get('[data-testid="rotation-token"]').element.value).toBe('');
    expect(wrapper.get('[role="alert"]').text()).toContain('账户不匹配');
  });

  it('updates, deletes and clears any Token field when navigating away', async () => {
    const api = makeApi({ credentials: [credential()] });
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(true);
    const { wrapper, router } = await mountView(api);
    await wrapper.get('[data-testid="credential-disable-credential-a"]').trigger('click');
    await flushPromises();
    expect(api.update).toHaveBeenCalledWith('credential-a', {
      expected_credential_version: 3,
      enabled: false,
    });
    await wrapper.get('[data-testid="credential-delete-credential-a"]').trigger('click');
    await flushPromises();
    expect(api.remove).toHaveBeenCalledWith('credential-a', 3);
    expect(confirm).toHaveBeenCalledOnce();

    await wrapper.get('[data-testid="rotate-credential-a"]').trigger('click');
    await wrapper.get('[data-testid="rotation-token"]').setValue('token-before-navigation');
    await router.push('/elsewhere');
    await flushPromises();
    expect(wrapper.find('[data-testid="rotation-token"]').exists()).toBe(false);
    expect(router.currentRoute.value.fullPath).not.toContain('token-before-navigation');
  });

  it('shows only current-user Credential risk counts on the home page', async () => {
    const HomeView = await loadHomeView();
    const api = makeApi({
      credentials: [
        credential({ account_binding_state: 'needs_reconfirmation', expiry_state: 'expiring_soon' }),
      ],
    });
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [
        { path: '/', name: 'home', component: HomeView },
        { path: '/account', name: 'account', component: { template: '<div />' } },
        { path: '/credentials', name: 'credentials', component: { template: '<div />' } },
      ],
    });
    await router.push('/');
    const wrapper = mount({ components: { RouterView }, template: '<RouterView />' }, {
      global: {
        plugins: [router],
        provide: {
          credentialApi: api,
          sessionStore: reactive({
            status: 'authenticated',
            user: { user_id: 'user-a', username: 'Alice' },
          }),
        },
      },
    });
    await flushPromises();

    expect(wrapper.text()).toContain('预约凭据状态');
    expect(wrapper.text()).toContain('1 个凭据需要重新确认账户连续性');
    expect(wrapper.text()).toContain('1 个凭据的 Token 即将到期');
    expect(wrapper.text()).not.toContain('synthetic-account-a');
    expect(wrapper.get('a[href="/credentials"]').text()).toBe('管理凭据');
  });

  it('adds a visible authenticated navigation link for Credential management', async () => {
    const App = await loadApp();
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [
        { path: '/', name: 'home', component: { template: '<div />' } },
        { path: '/account', name: 'account', component: { template: '<div />' } },
        { path: '/credentials', name: 'credentials', component: { template: '<div />' } },
        { path: '/login', name: 'login', component: { template: '<div />' } },
      ],
    });
    await router.push('/');
    const wrapper = mount(App, {
      global: {
        plugins: [router],
        provide: { sessionStore: reactive({ user: { user_id: 'user-a', username: 'Alice' } }) },
      },
    });

    expect(wrapper.get('nav a[href="/credentials"]').text()).toBe('预约凭据');
  });

  it('gives safe guidance for a same-account conflict and clears the Token', async () => {
    const token = 'synthetic-duplicate-token';
    const api = makeApi({
      credentials: [],
      create: vi.fn().mockRejectedValue(Object.assign(new Error('raw upstream text'), {
        code: 'credential_account_already_configured',
      })),
    });
    const { wrapper } = await mountView(api);
    await wrapper.get('[data-testid="credential-label"]').setValue('Duplicate');
    await wrapper.get('[data-testid="credential-token"]').setValue(token);
    await wrapper.get('[data-testid="credential-create"]').trigger('submit');
    await flushPromises();

    expect(wrapper.get('[data-testid="credential-token"]').element.value).toBe('');
    expect(wrapper.get('[role="alert"]').text()).toContain('重新启用或轮换已有凭据');
    expect(wrapper.text()).not.toContain(token);
    expect(wrapper.text()).not.toContain('raw upstream text');
  });
});
