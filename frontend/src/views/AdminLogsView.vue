<script setup>
import { computed, inject } from 'vue';
import { RouterLink } from 'vue-router';
import PageHeader from '../components/PageHeader.vue';
import RuntimeLogPanel from '../components/admin-logs/RuntimeLogPanel.vue';
const session = inject('sessionStore');
const authorized = computed(() => session?.status === 'authenticated' && session.user?.role === 'admin');
</script>
<template>
  <section class="admin-logs-page">
    <PageHeader title="运行日志"><RouterLink :to="{ name: 'admin-users' }" class="secondary-button">全站运行概览</RouterLink></PageHeader>
    <RuntimeLogPanel v-if="authorized" /><p v-else class="form-error" role="alert">管理员登录状态已失效，请重新登录。</p>
  </section>
</template>
<style scoped>.admin-logs-page{display:grid;gap:20px;min-width:0}</style>
