import { createApp } from 'vue';
import App from './App.vue';
import { createAdminInvitationApi } from './api/adminInvitations.js';
import { createCredentialApi } from './api/credentials.js';
import { httpClient } from './api/http.js';
import { createAppRouter } from './router.js';
import { createSessionStore } from './stores/session.js';

const sessionStore = createSessionStore();
const adminInvitationApi = createAdminInvitationApi(sessionStore);
const credentialApi = createCredentialApi(sessionStore);
const router = createAppRouter(sessionStore);

createApp(App)
  .provide('sessionStore', sessionStore)
  .provide('adminInvitationApi', adminInvitationApi)
  .provide('credentialApi', credentialApi)
  .provide('httpClient', httpClient)
  .use(router)
  .mount('#app');
