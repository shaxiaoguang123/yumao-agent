import { createMemoryHistory } from 'vue-router';
import { describe, expect, it, vi } from 'vitest';

async function loadRouterFactory() {
  const module = await import('./router.js').catch(() => null);
  expect(module).not.toBeNull();
  expect(module.createAppRouter).toBeTypeOf('function');
  return module.createAppRouter;
}

function makeStore() {
  return {
    status: 'unknown',
    initialRefreshComplete: false,
    user: null,
    refresh: vi.fn(),
  };
}

describe('auth router guard', () => {
  it('waits for the initial Session refresh before choosing a route', async () => {
    const createAppRouter = await loadRouterFactory();
    const store = makeStore();
    let resolveRefresh;
    store.refresh.mockImplementation(() => new Promise((resolve) => {
      resolveRefresh = () => {
        store.status = 'authenticated';
        store.initialRefreshComplete = true;
        resolve();
      };
    }));
    const router = createAppRouter(store, createMemoryHistory());
    let navigationFinished = false;
    const navigation = router.push('/account').finally(() => { navigationFinished = true; });

    await vi.waitFor(() => expect(store.refresh).toHaveBeenCalledOnce());
    expect(navigationFinished).toBe(false);
    resolveRefresh();
    await navigation;

    expect(router.currentRoute.value.name).toBe('account');
  });

  it('redirects to login only after a definitive anonymous refresh', async () => {
    const createAppRouter = await loadRouterFactory();
    const store = makeStore();
    store.refresh.mockImplementation(async () => {
      store.status = 'unauthenticated';
      store.initialRefreshComplete = true;
    });
    const router = createAppRouter(store, createMemoryHistory());

    await router.push('/account');

    expect(store.refresh).toHaveBeenCalledOnce();
    expect(router.currentRoute.value.name).toBe('login');
  });

  it('allows the requested protected route after a transient refresh failure', async () => {
    const createAppRouter = await loadRouterFactory();
    const store = makeStore();
    store.refresh.mockImplementation(async () => {
      store.status = 'unavailable';
      store.initialRefreshComplete = true;
    });
    const router = createAppRouter(store, createMemoryHistory());

    await router.push('/account');

    expect(store.refresh).toHaveBeenCalledOnce();
    expect(router.currentRoute.value.name).toBe('account');
  });

  it('does not redirect-loop on the login route when refresh is unavailable', async () => {
    const createAppRouter = await loadRouterFactory();
    const store = makeStore();
    store.refresh.mockImplementation(async () => {
      store.status = 'unavailable';
      store.initialRefreshComplete = true;
    });
    const router = createAppRouter(store, createMemoryHistory());

    await router.push('/login');

    expect(store.refresh).toHaveBeenCalledOnce();
    expect(router.currentRoute.value.name).toBe('login');
  });

  it('protects the Credential route and permits it after an authenticated refresh', async () => {
    const createAppRouter = await loadRouterFactory();
    const store = makeStore();
    store.status = 'unauthenticated';
    store.refresh.mockImplementation(async () => {
      store.status = 'authenticated';
      store.initialRefreshComplete = true;
    });
    const router = createAppRouter(store, createMemoryHistory());

    await router.push('/credentials');

    expect(store.refresh).toHaveBeenCalledOnce();
    expect(router.currentRoute.value.name).toBe('credentials');
    expect(router.currentRoute.value.meta.requiresAuth).toBe(true);
  });

  it('redirects an anonymous visitor away from the Credential route', async () => {
    const createAppRouter = await loadRouterFactory();
    const store = makeStore();
    store.refresh.mockImplementation(async () => {
      store.status = 'unauthenticated';
      store.initialRefreshComplete = true;
    });
    const router = createAppRouter(store, createMemoryHistory());

    await router.push('/credentials');

    expect(router.currentRoute.value.name).toBe('login');
  });

  it('allows an administrator after the initial Session refresh', async () => {
    const createAppRouter = await loadRouterFactory();
    const store = makeStore();
    store.refresh.mockImplementation(async () => {
      store.status = 'authenticated';
      store.user = { user_id: 'admin-a', username: 'Admin', role: 'admin' };
      store.initialRefreshComplete = true;
    });
    const router = createAppRouter(store, createMemoryHistory());

    await router.push('/admin/invitations');

    expect(router.currentRoute.value.name).toBe('admin-invitations');
    expect(router.currentRoute.value.meta.requiresAdmin).toBe(true);
  });

  it.each([
    ['ordinary user', { user_id: 'user-a', username: 'User', role: 'user' }],
    ['unknown role', { user_id: 'user-a', username: 'User', role: 'unknown' }],
    ['missing user role', { user_id: 'user-a', username: 'User' }],
  ])('redirects an authenticated %s away from the admin route', async (_label, user) => {
    const createAppRouter = await loadRouterFactory();
    const store = makeStore();
    store.status = 'authenticated';
    store.initialRefreshComplete = true;
    store.user = user;
    const router = createAppRouter(store, createMemoryHistory());

    await router.push('/admin/invitations');

    expect(router.currentRoute.value.name).toBe('home');
  });

  it('does not render the admin route when Session refresh is unavailable', async () => {
    const createAppRouter = await loadRouterFactory();
    const store = makeStore();
    store.refresh.mockImplementation(async () => {
      store.status = 'unavailable';
      store.user = null;
      store.initialRefreshComplete = true;
    });
    const router = createAppRouter(store, createMemoryHistory());

    await router.push('/admin/invitations');

    expect(router.currentRoute.value.name).toBe('home');
    expect(store.refresh).toHaveBeenCalledOnce();
  });
});
