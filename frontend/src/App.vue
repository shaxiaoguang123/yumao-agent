<script setup>
import { computed, inject } from 'vue';
import { RouterLink, RouterView, useRoute } from 'vue-router';
import AppIcon from './components/AppIcon.vue';
import './styles/design-system.css';
const sessionStore = inject('sessionStore');
const route = useRoute();
const contextTitle = computed(() => ({home:'工作台概览',credentials:'凭据管理',plans:'预约计划',account:'账户设置','ai-models':'AI模型设置','admin-invitations':'管理员工具'}[route.name] || '账户访问'));
</script>
<template>
 <div class="app-shell" :class="{ 'public-shell': !sessionStore?.user }">
  <a class="skip-link" href="#main-content">跳到主要内容</a>
  <header class="topbar">
   <RouterLink class="brand" :to="{name:'home'}"><span class="brand-mark"><AppIcon name="court" /></span><span><span class="brand-title">羽毛球预约工作台</span><small>YUMAO WORKSPACE</small></span></RouterLink>
   <p v-if="sessionStore?.user" class="nav-caption">工作空间</p>
   <nav aria-label="主导航" :class="{'admin-nav':sessionStore?.user?.role==='admin'}">
    <RouterLink v-if="sessionStore?.user" :to="{name:'home'}"><AppIcon name="home" />首页</RouterLink>
    <RouterLink v-if="sessionStore?.user" :to="{name:'credentials'}"><AppIcon name="shield" />预约凭据</RouterLink>
    <RouterLink v-if="sessionStore?.user" :to="{name:'plans'}"><AppIcon name="clock" />预约计划</RouterLink>
    <RouterLink v-if="sessionStore?.user?.role==='admin'" data-testid="admin-invitations-link" :to="{name:'admin-invitations'}"><AppIcon name="ticket" />邀请码管理</RouterLink>
    <RouterLink v-if="sessionStore?.user" :to="{name:'account'}"><AppIcon name="user" />账户</RouterLink>
    <RouterLink v-if="sessionStore?.user" :to="{name:'ai-models'}"><AppIcon name="settings" />设置 · AI模型</RouterLink>
    <RouterLink v-if="!sessionStore?.user" :to="{name:'login'}"><AppIcon name="user" />登录</RouterLink>
   </nav>
   <div v-if="sessionStore?.user" class="sidebar-note"><span class="availability-dot" />目前开放<p>账户、凭据与意向草稿</p><small>让每一步准备都清晰可见。</small></div>
  </header>
  <div class="workspace">
   <div v-if="sessionStore?.user" class="workspace-bar"><p>工作空间 <span>/</span> <strong>{{ contextTitle }}</strong></p><div class="workspace-user"><span class="avatar">{{ sessionStore.user.username?.slice(0,1).toUpperCase() }}</span><span>{{ sessionStore.user.username }}</span><span class="role-label">{{ sessionStore.user.role==='admin'?'管理员':'用户' }}</span></div></div>
   <main id="main-content" class="page-content" tabindex="-1"><RouterView /></main>
  </div>
 </div>
</template>
