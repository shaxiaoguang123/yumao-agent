import { createRouter, createWebHistory } from 'vue-router';
import AccountView from './views/AccountView.vue';
import AdminInvitationsView from './views/AdminInvitationsView.vue';
import AdminUsersView from './views/AdminUsersView.vue';
import AdminLogsView from './views/AdminLogsView.vue';
import CredentialView from './views/CredentialView.vue';
import HomeView from './views/HomeView.vue';
import InviteRegisterView from './views/InviteRegisterView.vue';
import LoginView from './views/LoginView.vue';
import PlansView from './views/PlansView.vue';
import AIModelsView from './views/AIModelsView.vue';
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

  router.beforeEach(async (to) => {
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
