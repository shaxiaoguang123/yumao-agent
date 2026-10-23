<script setup>
import { inject, nextTick, onMounted, onUnmounted, ref, watch } from 'vue';
import { RouterLink, RouterView, useRoute, useRouter } from 'vue-router';
import AppIcon from './components/AppIcon.vue';
import './styles/design-system.css';
const sessionStore = inject('sessionStore');
const route = useRoute();
const navigationPending = useRouter().navigationPending || ref(false);
const navElement = ref(null);
async function revealActiveNavigationItem() {
 await nextTick();
 const nav = navElement.value;
 const active = nav?.querySelector('.router-link-exact-active');
 if (nav && active && nav.scrollWidth > nav.clientWidth) {
  const navRect = nav.getBoundingClientRect();
  const activeRect = active.getBoundingClientRect();
  nav.scrollLeft += activeRect.left - navRect.left - (nav.clientWidth - active.offsetWidth) / 2;
 }
}
function closeNavigationMenus(event) {
 const menu = navElement.value?.querySelector('details[open]');
 if (!menu) return;
 menu.open = false;
 if (event?.key === 'Escape') menu.querySelector('summary')?.focus();
}
watch([() => route.fullPath, () => sessionStore?.user?.role], () => {
 closeNavigationMenus();
 revealActiveNavigationItem();
}, { flush: 'post' });
onMounted(() => {
 window.addEventListener('resize', revealActiveNavigationItem);
 revealActiveNavigationItem();
});
onUnmounted(() => window.removeEventListener('resize', revealActiveNavigationItem));
</script>
<template>
 <div class="app-shell" :class="{ 'public-shell': !sessionStore?.user }">
  <a class="skip-link" href="#main-content">跳到主要内容</a>
  <header class="topbar">
   <div class="topbar-inner">
   <RouterLink class="brand" :to="{name:'home'}"><span class="brand-mark"><AppIcon name="court" /></span><span><span class="brand-title">羽毛球预约工作台</span><small>YUMAO WORKSPACE</small></span></RouterLink>
   <nav ref="navElement" aria-label="主导航" :class="{'admin-nav':sessionStore?.user?.role==='admin'}" @keydown.esc="closeNavigationMenus">
    <RouterLink v-if="sessionStore?.user" :to="{name:'home'}"><AppIcon name="home" />首页</RouterLink>
    <RouterLink v-if="sessionStore?.user" :to="{name:'credentials'}"><AppIcon name="shield" />预约凭据</RouterLink>
    <RouterLink v-if="sessionStore?.user" :to="{name:'plans'}"><AppIcon name="clock" />预约计划</RouterLink>
    <details v-if="sessionStore?.user?.role==='admin'" class="nav-group" name="workspace-navigation" :class="{'is-active':String(route.name).startsWith('admin-')}">
     <summary><AppIcon name="user" />管理<AppIcon class="nav-chevron" name="down" /></summary>
     <div class="nav-menu">
      <RouterLink data-testid="admin-users-link" :to="{name:'admin-users'}"><AppIcon name="user" />用户管理</RouterLink>
      <RouterLink data-testid="admin-logs-link" :to="{name:'admin-logs'}"><AppIcon name="clock" />运行日志</RouterLink>
      <RouterLink data-testid="admin-invitations-link" :to="{name:'admin-invitations'}"><AppIcon name="ticket" />邀请码管理</RouterLink>
     </div>
    </details>
    <details v-if="sessionStore?.user" class="nav-group" name="workspace-navigation" :class="{'is-active':['account','ai-models'].includes(route.name)}">
     <summary><AppIcon name="settings" />设置<AppIcon class="nav-chevron" name="down" /></summary>
     <div class="nav-menu">
      <RouterLink :to="{name:'account'}"><AppIcon name="user" />账户</RouterLink>
      <RouterLink :to="{name:'ai-models'}"><AppIcon name="settings" />设置 · AI模型</RouterLink>
     </div>
    </details>
    <RouterLink v-if="!sessionStore?.user" :to="{name:'login'}"><AppIcon name="user" />登录</RouterLink>
   </nav>
   <RouterLink v-if="sessionStore?.user" class="workspace-profile" :to="{name:'account'}" aria-label="当前账户设置">
    <span class="avatar">{{ sessionStore.user.username?.slice(0,1).toUpperCase() }}</span>
    <span class="profile-name">{{ sessionStore.user.username }}</span>
   </RouterLink>
   </div>
  </header>
  <div class="workspace">
   <p v-if="navigationPending" class="navigation-progress" role="status">正在切换页面…</p>
   <main id="main-content" class="page-content" tabindex="-1" :aria-busy="navigationPending"><RouterView /></main>
  </div>
 </div>
</template>
<style scoped>
.navigation-progress{position:fixed;top:76px;left:50%;transform:translateX(-50%);z-index:80;margin:0;padding:8px 16px;border:1px solid var(--line);border-radius:999px;background:var(--surface);box-shadow:var(--shadow);color:var(--muted);font-size:13px;pointer-events:none}
</style>
