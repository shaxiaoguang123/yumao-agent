import { defineConfig } from 'vite';
import vue from '@vitejs/plugin-vue';
const upstream = process.env.PLAN_QA_BACKEND;
if (!/^http:\/\/127\.0\.0\.1:\d+$/.test(upstream || '')) throw new Error('isolated loopback backend is required');
export default defineConfig({plugins:[vue()],envDir:false,cacheDir:process.env.PLAN_QA_CACHE,server:{host:'127.0.0.1',port:Number(process.env.PLAN_QA_PORT),strictPort:true,proxy:{'/api':{target:upstream,changeOrigin:true}}}});
