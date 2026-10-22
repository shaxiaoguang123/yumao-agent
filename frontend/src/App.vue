<script setup>
import { inject, nextTick, onMounted, onUnmounted, ref, watch } from 'vue';
import { RouterLink, RouterView, useRoute } from 'vue-router';
import AppIcon from './components/AppIcon.vue';
import './styles/design-system.css';
const sessionStore = inject('sessionStore');
const route = useRoute();
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
watch([() => route.fullPath, () => sessionStore?.user?.role], revealActiveNavigationItem, { flush: 'post' });
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
   <RouterLink class="brand" :to="{name:'home'}"><span class="brand-mark"><AppIcon name="court" /></span><span><span class="brand-title">羽毛球预约工作台</span><small>YUMAO WORKSPACE</small></span></RouterLink>
   <p v-if="sessionStore?.user" class="nav-caption">工作空间</p>
   <nav ref="navElement" aria-label="主导航" :class="{'admin-nav':sessionStore?.user?.role==='admin'}">
    <RouterLink v-if="sessionStore?.user" :to="{name:'home'}"><AppIcon name="home" />首页</RouterLink>
    <RouterLink v-if="sessionStore?.user" :to="{name:'credentials'}"><AppIcon name="shield" />预约凭据</RouterLink>
    <RouterLink v-if="sessionStore?.user" :to="{name:'plans'}"><AppIcon name="clock" />预约计划</RouterLink>
    <RouterLink v-if="sessionStore?.user?.role==='admin'" data-testid="admin-users-link" :to="{name:'admin-users'}"><AppIcon name="user" />用户管理</RouterLink>
    <RouterLink v-if="sessionStore?.user?.role==='admin'" data-testid="admin-logs-link" :to="{name:'admin-logs'}"><AppIcon name="clock" />运行日志</RouterLink>
    <RouterLink v-if="sessionStore?.user?.role==='admin'" data-testid="admin-invitations-link" :to="{name:'admin-invitations'}"><AppIcon name="ticket" />邀请码管理</RouterLink>
    <RouterLink v-if="sessionStore?.user" :to="{name:'account'}"><AppIcon name="user" />账户</RouterLink>
    <RouterLink v-if="sessionStore?.user" :to="{name:'ai-models'}"><AppIcon name="settings" />设置 · AI模型</RouterLink>
    <RouterLink v-if="!sessionStore?.user" :to="{name:'login'}"><AppIcon name="user" />登录</RouterLink>
   </nav>
   <div v-if="sessionStore?.user" class="sidebar-user">
    <span class="avatar">{{ sessionStore.user.username?.slice(0,1).toUpperCase() }}</span>
    <span class="sidebar-user-meta">
     <strong>{{ sessionStore.user.username }}</strong>
     <span>{{ sessionStore.user.role==='admin'?'管理员':'用户' }}</span>
    </span>
   </div>
   <div v-if="sessionStore?.user" class="sidebar-note"><span class="availability-dot" />目前开放<p>账户、凭据与意向草稿</p><small>让每一步准备都清晰可见。</small></div>
  </header>
  <div class="workspace">
   <main id="main-content" class="page-content" tabindex="-1"><RouterView /></main>
  </div>
 </div>
</template>
