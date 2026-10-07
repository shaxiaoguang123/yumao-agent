import { reactive } from 'vue';
import { createHttpClient } from '../api/http.js';

const LOGOUT_UNCONFIRMED = '退出状态未确认，请重试';

export function createSessionStore({ client: providedClient } = {}) {
  const store = reactive({
    user: null,
    csrfToken: '',
    status: 'unknown',
    initialRefreshComplete: false,
    errorMessage: '',
    logoutUnconfirmed: false,
    logoutMessage: '',
  });

  function clearAuth() {
    store.user = null;
    store.csrfToken = '';
    store.status = 'unauthenticated';
    store.logoutUnconfirmed = false;
    store.logoutMessage = '';
    store.errorMessage = '';
  }

  const client = providedClient || createHttpClient({
    getCsrfToken: () => store.csrfToken,
    onSessionInvalid: () => {
      clearAuth();
      store.initialRefreshComplete = true;
    },
  });

  function acceptSession(payload) {
    store.user = payload.user;
    store.csrfToken = payload.csrf_token;
    store.status = 'authenticated';
    store.initialRefreshComplete = true;
    store.errorMessage = '';
    store.logoutUnconfirmed = false;
    store.logoutMessage = '';
  }

  store.refresh = async () => {
    try {
      const payload = await client.request('/api/auth/session');
      if (payload?.authenticated === true && payload.user && payload.csrf_token) {
        acceptSession(payload);
      } else if (payload?.authenticated === false) {
        clearAuth();
        store.initialRefreshComplete = true;
      } else {
        throw new Error('invalid_session_response');
      }
    } catch (error) {
      store.initialRefreshComplete = true;
      if (error?.sessionInvalid) {
        clearAuth();
      } else {
        store.status = 'unavailable';
        store.errorMessage = '暂时无法确认登录状态，请重试';
      }
    }
    return store.status;
  };

  store.login = async (username, password) => {
    try {
      const payload = await client.request('/api/auth/login', {
        method: 'POST',
        body: { username, password },
      });
      if (payload?.authenticated !== true || !payload.user || !payload.csrf_token) {
        throw new Error('invalid_login_response');
      }
      acceptSession(payload);
      return true;
    } catch (error) {
      if (error?.sessionInvalid) {
        clearAuth();
        store.initialRefreshComplete = true;
      }
      store.errorMessage = error?.code === 'invalid_credentials'
        ? '用户名或密码错误'
        : '登录暂不可用，请重试';
      return false;
    }
  };

  store.logout = async () => {
    try {
      await client.request('/api/auth/logout', { method: 'POST' });
      clearAuth();
      store.initialRefreshComplete = true;
      return true;
    } catch (error) {
      if (error?.sessionInvalid) {
        clearAuth();
        store.initialRefreshComplete = true;
        return true;
      }
      store.logoutUnconfirmed = true;
      store.logoutMessage = LOGOUT_UNCONFIRMED;
      return false;
    }
  };

  store.changePassword = async (currentPassword, newPassword) => {
    try {
      await client.request('/api/auth/change-password', {
        method: 'POST',
        body: {
          current_password: currentPassword,
          new_password: newPassword,
        },
      });
      clearAuth();
      store.initialRefreshComplete = true;
      return true;
    } catch (error) {
      if (error?.sessionInvalid) {
        clearAuth();
        store.initialRefreshComplete = true;
      }
      store.errorMessage = error?.code === 'invalid_credentials'
        ? '当前密码不正确'
        : '密码修改失败，请检查输入后重试';
      return false;
    }
  };

  return store;
}
