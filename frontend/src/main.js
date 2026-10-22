import { createApp } from 'vue';
import App from './App.vue';
import { createAdminInvitationApi } from './api/adminInvitations.js';
import { createAdminUsersApi } from './api/adminUsers.js';
import { createDiagnosticsApi } from './api/diagnostics.js';
import { createCredentialApi } from './api/credentials.js';
import { createPlanApi } from './api/plans.js';
import { createOrderApi } from './api/orders.js';
import { createAIModelsApi } from './api/aiModels.js';
import { createPlanningProposalApi } from './api/planningProposals.js';
import { createIntentPlanningProposalApi } from './api/intentPlanningProposals.js';
import { createAvailabilitySimulationApi } from './api/availabilitySimulation.js';
import { createLiveAvailabilityApi } from './api/liveAvailability.js';
import { httpClient } from './api/http.js';
import { createAppRouter } from './router.js';
import { createSessionStore } from './stores/session.js';

const sessionStore = createSessionStore();
const adminInvitationApi = createAdminInvitationApi(sessionStore);
const adminUsersApi = createAdminUsersApi(sessionStore);
const credentialApi = createCredentialApi(sessionStore);
const aiModelsApi = createAIModelsApi(sessionStore);
const router = createAppRouter(sessionStore, undefined, { credentialApi });

createApp(App)
  .provide('sessionStore', sessionStore)
  .provide('adminInvitationApi', adminInvitationApi)
  .provide('adminUsersApi', adminUsersApi)
  .provide('diagnosticsApi', createDiagnosticsApi(sessionStore))
  .provide('credentialApi', credentialApi)
  .provide('planApi', createPlanApi(sessionStore))
  .provide('orderApi', createOrderApi(sessionStore))
  .provide('aiModelsApi', aiModelsApi)
  .provide('planningProposalApi', createPlanningProposalApi(sessionStore))
  .provide('intentPlanningProposalApi', createIntentPlanningProposalApi(sessionStore))
  .provide('availabilitySimulationApi', createAvailabilitySimulationApi(sessionStore))
  .provide('liveAvailabilityApi', createLiveAvailabilityApi(sessionStore))
  .provide('httpClient', httpClient)
  .use(router)
  .mount('#app');
