import { defineConfig } from 'vite';
import vue from '@vitejs/plugin-vue';

// Never load local .env files or forward an unmocked API to Flask/upstream.
export default defineConfig({
  plugins: [vue()],
  envDir: false,
  cacheDir: process.env.BROWSER_QA_CACHE,
  server: {
    host: '127.0.0.1',
    port: Number(process.env.BROWSER_QA_PORT),
    strictPort: true,
    proxy: {},
  },
});
