import { mount } from '@vue/test-utils';
import { createMemoryHistory, createRouter } from 'vue-router';
import { describe, expect, it } from 'vitest';
import { reactive } from 'vue';
import App from './App.vue';

const emptyView = { template: '<div />' };

async function mountApp(role) {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/', name: 'home', component: emptyView },
      { path: '/credentials', name: 'credentials', component: emptyView },
      { path: '/account', name: 'account', component: emptyView },
      { path: '/login', name: 'login', component: emptyView },
      { path: '/admin/invitations', name: 'admin-invitations', component: emptyView },
    ],
  });
  await router.push('/');
  await router.isReady();
  const sessionStore = reactive({
    user: role ? { user_id: 'user-test', username: 'Test User', role } : null,
  });
  const wrapper = mount(App, {
    global: {
      plugins: [router],
      provide: { sessionStore },
    },
  });
  return { wrapper, router, sessionStore };
}

describe('application navigation', () => {
  it('shows invitation management only for an administrator', async () => {
    const { wrapper } = await mountApp('admin');

    expect(wrapper.get('[data-testid="admin-invitations-link"]').attributes('href'))
      .toBe('/admin/invitations');
  });

  it('hides invitation management from an ordinary user and anonymous visitor', async () => {
    for (const role of ['user', null]) {
      const { wrapper } = await mountApp(role);
      expect(wrapper.find('[data-testid="admin-invitations-link"]').exists()).toBe(false);
      wrapper.unmount();
    }
  });

  it('updates role navigation without rebuilding the application when Session is cleared', async () => {
    const { wrapper, sessionStore } = await mountApp('admin');
    expect(wrapper.get('nav[aria-label="主导航"]').findAll('a').map((a) => a.text()))
      .toEqual(['首页', '预约凭据', '邀请码管理', '账户']);
    sessionStore.user = null;
    await wrapper.vm.$nextTick();
    expect(wrapper.get('nav').findAll('a').map((a) => a.text())).toEqual(['登录']);
    wrapper.unmount();
  });
});
