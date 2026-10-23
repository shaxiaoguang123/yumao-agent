import { flushPromises, mount } from '@vue/test-utils';
import { createMemoryHistory, createRouter } from 'vue-router';
import { describe, expect, it, vi } from 'vitest';
import { reactive } from 'vue';
import App from './App.vue';

const emptyView = { template: '<div />' };

async function mountApp(role) {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/', name: 'home', component: emptyView },
      { path: '/plans', name: 'plans', component: { template: '<div />' } },
      { path: '/credentials', name: 'credentials', component: emptyView },
      { path: '/account', name: 'account', component: emptyView },
      { path: '/settings/ai-models', name: 'ai-models', component: emptyView },
      { path: '/login', name: 'login', component: emptyView },
      { path: '/admin', name: 'admin-users', component: emptyView },
      { path: '/admin/logs', name: 'admin-logs', component: emptyView },
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

    expect(wrapper.get('[data-testid="admin-users-link"]').attributes('href')).toBe('/admin');
    expect(wrapper.get('[data-testid="admin-logs-link"]').attributes('href')).toBe('/admin/logs');
    expect(wrapper.get('[data-testid="admin-invitations-link"]').attributes('href'))
      .toBe('/admin/invitations');
  });

  it('hides invitation management from an ordinary user and anonymous visitor', async () => {
    for (const role of ['user', null]) {
      const { wrapper } = await mountApp(role);
      expect(wrapper.find('[data-testid="admin-users-link"]').exists()).toBe(false);
      expect(wrapper.find('[data-testid="admin-logs-link"]').exists()).toBe(false);
      expect(wrapper.find('[data-testid="admin-invitations-link"]').exists()).toBe(false);
      wrapper.unmount();
    }
  });

  it('scrolls the navigation container to the active route', async () => {
    const addListener = vi.spyOn(window, 'addEventListener');
    const removeListener = vi.spyOn(window, 'removeEventListener');
    const { wrapper, router } = await mountApp('admin');
    await flushPromises();
    const resizeHandler = addListener.mock.calls.filter(([type]) => type === 'resize').at(-1)?.[1];
    const nav = wrapper.get('nav').element;
    const activeLink = wrapper.get('[data-testid=admin-logs-link]').element;
    let navWidth = 200;
    Object.defineProperty(nav, 'clientWidth', { configurable: true, get: () => navWidth });
    Object.defineProperty(nav, 'scrollWidth', { configurable: true, value: 900 });
    Object.defineProperty(nav, 'getBoundingClientRect', { configurable: true, value: () => ({ left: 16 }) });
    Object.defineProperty(activeLink, 'offsetWidth', { configurable: true, value: 80 });
    Object.defineProperty(activeLink, 'getBoundingClientRect', { configurable: true, value: () => ({ left: 16 + 700 - nav.scrollLeft }) });
    nav.scrollLeft = 120;

    await router.push('/admin/logs');
    await flushPromises();

    expect(nav.scrollLeft).toBe(640);
    expect(wrapper.get('[data-testid=admin-logs-link]').attributes('aria-current')).toBe('page');

    navWidth = 160;
    window.dispatchEvent(new Event('resize'));
    await flushPromises();
    expect(nav.scrollLeft).toBe(660);
    wrapper.unmount();
    expect(removeListener).toHaveBeenCalledWith('resize', resizeHandler);
    addListener.mockRestore();
    removeListener.mockRestore();
  });

  it('keeps grouped destinations and closes the menu after navigation or Escape', async () => {
    const { wrapper, router } = await mountApp('admin');
    const menu = wrapper.get('.nav-group');
    menu.element.open = true;
    await router.push('/admin/logs');
    await flushPromises();
    expect(menu.classes()).toContain('is-active');
    expect(menu.element.open).toBe(false);
    expect(menu.get('[data-testid="admin-logs-link"]').attributes('aria-current')).toBe('page');
    menu.element.open = true;
    await menu.trigger('keydown', { key: 'Escape' });
    expect(menu.element.open).toBe(false);
    wrapper.unmount();
  });

  it('updates role navigation without rebuilding the application when Session is cleared', async () => {
    const { wrapper, sessionStore } = await mountApp('admin');
    expect(wrapper.get('nav[aria-label="主导航"]').findAll('a').map((a) => a.text()))
      .toEqual(['首页', '预约凭据', '预约计划', '用户管理', '运行日志', '邀请码管理', '账户', '设置 · AI模型']);
    sessionStore.user = null;
    await wrapper.vm.$nextTick();
    expect(wrapper.get('nav').findAll('a').map((a) => a.text())).toEqual(['登录']);
    wrapper.unmount();
  });
});
