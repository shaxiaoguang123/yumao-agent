import { createApp } from 'vue';
import App from './App.vue';
import { createAdminInvitationApi } from './api/adminInvitations.js';
import { createCredentialApi } from './api/credentials.js';
import { createPlanApi } from './api/plans.js';
import { createAIModelsApi } from './api/aiModels.js';
import { createPlanningProposalApi } from './api/planningProposals.js';
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
  .provide('planApi', createPlanApi(sessionStore))
  .provide('aiModelsApi', createAIModelsApi(sessionStore))
  .provide('planningProposalApi', createPlanningProposalApi(sessionStore))
  .provide('httpClient', httpClient)
  .use(router)
  .mount('#app');
