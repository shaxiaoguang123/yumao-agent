import { flushPromises, mount } from '@vue/test-utils';
import { reactive } from 'vue';
import { createMemoryHistory, createRouter } from 'vue-router';
import { describe, expect, it, vi } from 'vitest';

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
});
