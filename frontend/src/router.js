import { createRouter, createWebHistory } from 'vue-router';
import AccountView from './views/AccountView.vue';
import AdminInvitationsView from './views/AdminInvitationsView.vue';
import CredentialView from './views/CredentialView.vue';
import HomeView from './views/HomeView.vue';
import InviteRegisterView from './views/InviteRegisterView.vue';
import LoginView from './views/LoginView.vue';
import PlansView from './views/PlansView.vue';

export function createAppRouter(sessionStore, history = createWebHistory()) {
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
        path: '/admin/invitations',
        name: 'admin-invitations',
        component: AdminInvitationsView,
        meta: { requiresAuth: true, requiresAdmin: true },
      },
      { path: '/plans', name:'plans', component:PlansView, meta:{requiresAuth:true} },
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
    return true;
  });

  return router;
}
