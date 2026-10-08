<script setup>
import { inject } from 'vue';
import { RouterLink, RouterView } from 'vue-router';

const sessionStore = inject('sessionStore');
</script>

<template>
  <div class="app-shell">
    <header class="topbar">
      <RouterLink class="brand" :to="{ name: 'home' }">羽毛球预约工作台</RouterLink>
      <nav aria-label="主导航">
        <RouterLink v-if="sessionStore?.user" :to="{ name: 'home' }">首页</RouterLink>
        <RouterLink v-if="sessionStore?.user" :to="{ name: 'credentials' }">预约凭据</RouterLink>
        <RouterLink v-if="sessionStore?.user" :to="{ name: 'account' }">账户</RouterLink>
        <RouterLink v-if="!sessionStore?.user" :to="{ name: 'login' }">登录</RouterLink>
      </nav>
    </header>
    <main class="page-content">
      <RouterView />
    </main>
  </div>
</template>

<style>
:root {
  font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  color: #182230;
  background: #f4f6f8;
  font-synthesis: none;
  text-rendering: optimizeLegibility;
}

* { box-sizing: border-box; }
body { margin: 0; min-width: 320px; min-height: 100vh; }
button, input { font: inherit; }
a { color: #146c5b; text-decoration: none; }
a:hover { text-decoration: underline; }
.app-shell { min-height: 100vh; }
.topbar { display: flex; align-items: center; justify-content: space-between; gap: 1.5rem; padding: 1rem clamp(1rem, 5vw, 4rem); background: #fff; border-bottom: 1px solid #e1e7ec; }
.brand { color: #163b35; font-weight: 750; letter-spacing: .01em; }
.topbar nav { display: flex; gap: 1.25rem; }
.page-content { width: min(100% - 2rem, 68rem); margin: 2.5rem auto; }
.panel { width: min(100%, 34rem); margin: 3rem auto; padding: clamp(1.25rem, 4vw, 2rem); background: #fff; border: 1px solid #e4e9ed; border-radius: 1rem; box-shadow: 0 12px 32px rgb(23 41 56 / 5%); }
.panel h1 { margin: 0 0 .5rem; font-size: clamp(1.4rem, 4vw, 1.9rem); }
.muted { color: #65717e; line-height: 1.6; }
.form-stack { display: grid; gap: 1rem; margin-top: 1.5rem; }
.field { display: grid; gap: .4rem; color: #334155; font-size: .92rem; font-weight: 600; }
.field input { width: 100%; padding: .75rem .85rem; border: 1px solid #cbd5df; border-radius: .6rem; background: #fff; color: #182230; }
.field input:focus { outline: 3px solid rgb(20 108 91 / 16%); border-color: #146c5b; }
.primary-button, .secondary-button { min-height: 2.75rem; padding: .65rem 1rem; border: 0; border-radius: .6rem; cursor: pointer; font-weight: 700; }
.primary-button { color: white; background: #146c5b; }
.primary-button:disabled { opacity: .6; cursor: wait; }
.secondary-button { color: #263747; background: #eaf0f2; }
.form-error, [role="alert"] { color: #a32626; }
.form-success { color: #176348; }
.inline-links { display: flex; gap: 1rem; margin-top: 1.25rem; }
</style>
