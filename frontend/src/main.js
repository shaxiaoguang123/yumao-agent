import { createApp } from 'vue';
import App from './App.vue';
import { httpClient } from './api/http.js';
import { createAppRouter } from './router.js';
import { createSessionStore } from './stores/session.js';

const sessionStore = createSessionStore();
const router = createAppRouter(sessionStore);

createApp(App)
  .provide('sessionStore', sessionStore)
  .provide('httpClient', httpClient)
  .use(router)
  .mount('#app');
