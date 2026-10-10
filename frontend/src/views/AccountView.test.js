import { flushPromises, mount } from '@vue/test-utils';
import { reactive } from 'vue';
import { createMemoryHistory, createRouter } from 'vue-router';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { enableAutoUnmount } from '@vue/test-utils';

enableAutoUnmount(afterEach);

async function loadView() {
  const module = await import('./AccountView.vue').catch(() => null);
  expect(module).not.toBeNull();
  expect(module.default).toBeTruthy();
  return module.default;
}

function makeRouter() {
  const emptyView = { template: '<div />' };
  return createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/account', name: 'account', component: emptyView },
      { path: '/login', name: 'login', component: emptyView },
    ],
  });
}

describe('account view logout feedback', () => {
  it('does not claim logout succeeded when the server result is unknown', async () => {
    const AccountView = await loadView();
    const sessionStore = reactive({
      user: { user_id: 'user-1', username: 'Alice', role: 'user' },
      status: 'authenticated',
      logoutUnconfirmed: false,
      logoutMessage: '',
      logout: vi.fn(async () => {
        sessionStore.logoutUnconfirmed = true;
        sessionStore.logoutMessage = '退出状态未确认，请重试';
        return false;
      }),
    });
    const router = makeRouter();
    await router.push('/account');
    const wrapper = mount(AccountView, {
      global: { plugins: [router], provide: { sessionStore } },
    });

    await wrapper.get('[data-testid="logout"]').trigger('click');

    expect(sessionStore.logout).toHaveBeenCalledOnce();
    expect(wrapper.get('[role="alert"]').text()).toBe('退出状态未确认，请重试');
    expect(wrapper.text()).not.toContain('已退出');
  });

  it('navigates to login only after the server confirms logout', async () => {
    const AccountView = await loadView();
    const router = makeRouter();
    await router.push('/account');
    const sessionStore = reactive({
      user: { user_id: 'user-1', username: 'Alice', role: 'user' },
      status: 'authenticated',
      logoutUnconfirmed: false,
      logoutMessage: '',
      logout: vi.fn(async () => true),
    });
    const wrapper = mount(AccountView, {
      global: { plugins: [router], provide: { sessionStore } },
    });

    await wrapper.get('[data-testid="logout"]').trigger('click');
    await flushPromises();

    expect(router.currentRoute.value.name).toBe('login');
  });

  it('shows a retryable unavailable state without password or logout controls', async () => {
    const AccountView = await loadView();
    const sessionStore = reactive({
      user: null,
      status: 'unavailable',
      errorMessage: '暂时无法确认登录状态，请重试',
      refresh: vi.fn(),
      logoutUnconfirmed: false,
      logoutMessage: '',
    });
    const router = makeRouter();
    await router.push('/account');
    const wrapper = mount(AccountView, {
      global: { plugins: [router], provide: { sessionStore } },
    });

    expect(wrapper.get('[role="alert"]').text()).toContain('暂时无法确认登录状态');
    expect(wrapper.find('[data-testid="logout"]').exists()).toBe(false);
    await wrapper.get('[data-testid="retry-session"]').trigger('click');
    expect(sessionStore.refresh).toHaveBeenCalledOnce();
  });
});

async function mountPasswordView(changePassword) {
  const AccountView = await loadView();
  const sessionStore = reactive({
    user: { user_id: 'synthetic-user', username: 'Test User', role: 'user' },
    status: 'authenticated',
    errorMessage: '密码修改失败，请检查输入后重试',
    changePassword,
  });
  const router = makeRouter();
  await router.push('/account');
  const wrapper = mount(AccountView, {
    global: { plugins: [router], provide: { sessionStore } },
  });
  await wrapper.get('input[autocomplete="current-password"]').setValue('synthetic-current-password');
  await wrapper.get('input[autocomplete="new-password"]').setValue('synthetic-new-password');
  return { wrapper, sessionStore };
}

describe('password submission lifecycle', () => {
  it('locks synchronously during a pending request, including direct and repeated form calls', async () => {
    let resolveChange;
    const change = vi.fn(() => new Promise((resolve) => { resolveChange = resolve; }));
    const { wrapper } = await mountPasswordView(change);
    await wrapper.get('form').trigger('submit');
    await wrapper.get('form').trigger('submit');
    wrapper.vm.$.setupState.changePassword();

    expect(change).toHaveBeenCalledOnce();
    expect(wrapper.get('button[type="submit"]').element.disabled).toBe(true);
    expect(wrapper.get('[role="status"]').text()).toContain('正在修改密码');
    expect(wrapper.findAll('input').every((input) => input.element.disabled)).toBe(true);

    resolveChange(false);
    await flushPromises();
    expect(wrapper.get('button[type="submit"]').element.disabled).toBe(false);
    expect(wrapper.findAll('input').every((input) => input.element.value === '')).toBe(true);
    expect(wrapper.get('[role="status"]').text()).toContain('密码修改失败');
  });

  it('clears passwords and prevents further requests after successful Session revocation', async () => {
    let resolveChange;
    const change = vi.fn(() => new Promise((resolve) => { resolveChange = resolve; }));
    const { wrapper, sessionStore } = await mountPasswordView(change);
    await wrapper.get('form').trigger('submit');
    sessionStore.status = 'unauthenticated';
    sessionStore.user = null;
    resolveChange(true);
    await flushPromises();

    expect(wrapper.text()).toContain('密码已修改，请重新登录');
    expect(wrapper.find('form').exists()).toBe(false);
    expect(wrapper.vm.$.setupState.currentPassword).toBe('');
    expect(wrapper.vm.$.setupState.newPassword).toBe('');
    await wrapper.vm.$.setupState.changePassword();
    expect(change).toHaveBeenCalledOnce();
  });

  it('cleans up and unlocks after an unexpected request rejection without exposing its message', async () => {
    const change = vi.fn().mockRejectedValue(new Error('synthetic-private-error-detail'));
    const { wrapper } = await mountPasswordView(change);
    await wrapper.get('form').trigger('submit');
    await flushPromises();

    expect(wrapper.get('button[type="submit"]').element.disabled).toBe(false);
    expect(wrapper.findAll('input').every((input) => input.element.value === '')).toBe(true);
    expect(wrapper.text()).toContain('密码修改失败');
    expect(wrapper.text()).not.toContain('synthetic-private-error-detail');
  });

  it('clears sensitive state on unmount and ignores a late response', async () => {
    let resolveChange;
    const change = vi.fn(() => new Promise((resolve) => { resolveChange = resolve; }));
    const { wrapper } = await mountPasswordView(change);
    const state = wrapper.vm.$.setupState;
    await wrapper.get('form').trigger('submit');
    wrapper.unmount();

    expect(state.currentPassword).toBe('');
    expect(state.newPassword).toBe('');
    expect(state.passwordSubmitting).toBe(false);
    resolveChange(true);
    await flushPromises();
    expect(state.passwordMessage).toBe('');
  });

  it('clears inputs when the Session becomes unavailable during a pending request', async () => {
    let resolveChange;
    const change = vi.fn(() => new Promise((resolve) => { resolveChange = resolve; }));
    const { wrapper, sessionStore } = await mountPasswordView(change);
    await wrapper.get('form').trigger('submit');
    sessionStore.status = 'unavailable';
    await flushPromises();
    expect(wrapper.vm.$.setupState.currentPassword).toBe('');
    expect(wrapper.vm.$.setupState.newPassword).toBe('');
    await wrapper.vm.$.setupState.changePassword();
    expect(change).toHaveBeenCalledOnce();
    resolveChange(false);
    await flushPromises();
    expect(wrapper.vm.$.setupState.passwordSubmitting).toBe(false);
  });
});
