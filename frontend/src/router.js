import { createRouter, createWebHistory } from 'vue-router';
import { shallowRef } from 'vue';
const AccountView = () => import('./views/AccountView.vue');
const AdminInvitationsView = () => import('./views/AdminInvitationsView.vue');
const AdminUsersView = () => import('./views/AdminUsersView.vue');
const AdminLogsView = () => import('./views/AdminLogsView.vue');
const CredentialView = () => import('./views/CredentialView.vue');
const HomeView = () => import('./views/HomeView.vue');
const InviteRegisterView = () => import('./views/InviteRegisterView.vue');
const LoginView = () => import('./views/LoginView.vue');
const PlansView = () => import('./views/PlansView.vue');
const AIModelsView = () => import('./views/AIModelsView.vue');
import { planSetupRequirement } from './utils/credentialReadiness.js';

export function createAppRouter(sessionStore, history = createWebHistory(), { credentialApi } = {}) {
  const router = createRouter({
    history,
    routes: [
      { path: '/login', name: 'login', component: LoginView },
      { path: '/register', name: 'register', component: InviteRegisterView },
      {
        path: '/',
        name: 'home',
        component: HomeView,
        meta: { requiresAuth: true },
      },
      {
        path: '/account',
        name: 'account',
        component: AccountView,
        meta: { requiresAuth: true },
      },
      {
        path: '/credentials',
        name: 'credentials',
        component: CredentialView,
        meta: { requiresAuth: true },
      },
      {
        path: '/admin',
        name: 'admin-users',
        component: AdminUsersView,
        meta: { requiresAuth: true, requiresAdmin: true },
      },
      {
        path: '/admin/invitations',
        name: 'admin-invitations',
        component: AdminInvitationsView,
        meta: { requiresAuth: true, requiresAdmin: true },
      },
      { path: '/admin/logs', name: 'admin-logs', component: AdminLogsView, meta: { requiresAuth: true, requiresAdmin: true } },
      { path: '/plans', name:'plans', component:PlansView, meta:{requiresAuth:true,requiresPlanSetup:true} },
      { path: '/settings/ai-models', name:'ai-models', component:AIModelsView, meta:{requiresAuth:true} },
      { path: '/:pathMatch(.*)*', redirect: { name: 'home' } },
    ],
  });

  router.navigationPending = shallowRef(false);
  let pendingTarget;
  router.afterEach(to => { if (to === pendingTarget) router.navigationPending.value = false; });
  router.onError(() => { router.navigationPending.value = false; });
  router.beforeEach(async (to) => {
    pendingTarget = to;
    router.navigationPending.value = true;
    if (!sessionStore.initialRefreshComplete) {
      try {
        await sessionStore.refresh();
      } catch {
        sessionStore.initialRefreshComplete = true;
        if (!sessionStore.user) sessionStore.status = 'unavailable';
      }
    }

    if (to.meta.requiresAuth && sessionStore.status === 'unauthenticated') {
      return { name: 'login', replace: true };
    }
    if (
      to.meta.requiresAdmin
      && (
        sessionStore.status !== 'authenticated'
        || sessionStore.user?.role !== 'admin'
      )
    ) {
      return { name: 'home', replace: true };
    }
    if (
      (to.name === 'login' || to.name === 'register')
      && sessionStore.status === 'authenticated'
    ) {
      return { name: 'home', replace: true };
    }
    if (to.meta.requiresPlanSetup && sessionStore.status === 'authenticated') {
      if (!credentialApi) {
        return { name: 'credentials', query: { returnTo: 'plans', setup: 'check_failed' }, replace: true };
      }
      try {
        const result = await credentialApi.list();
        const setup = planSetupRequirement(result?.credentials, { readOnly: to.query.tab === 'orders' });
        if (setup) {
          return { name: 'credentials', query: { returnTo: 'plans', setup }, replace: true };
        }
      } catch {
        if (sessionStore.status === 'unauthenticated') return { name: 'login', replace: true };
        return { name: 'credentials', query: { returnTo: 'plans', setup: 'check_failed' }, replace: true };
      }
    }
    return true;
  });

  return router;
}
