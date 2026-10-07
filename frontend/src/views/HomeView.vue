<script setup>
import { inject } from 'vue';
import { RouterLink } from 'vue-router';

const sessionStore = inject('sessionStore');
</script>

<template>
  <section class="panel">
    <template v-if="sessionStore.status === 'unavailable'">
      <h1>暂时无法确认登录状态</h1>
      <p class="muted" role="alert">{{ sessionStore.errorMessage || '请检查连接后重试。' }}</p>
      <button class="secondary-button" type="button" @click="sessionStore.refresh()">重试</button>
    </template>
    <template v-else>
      <h1>你好，{{ sessionStore.user?.username || '用户' }}</h1>
      <p class="muted">身份基础已就绪。预约计划和自动执行功能将在后续阶段接入。</p>
      <RouterLink :to="{ name: 'account' }">管理账户与密码</RouterLink>
    </template>
  </section>
</template>
