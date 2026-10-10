<script setup>
import { inject, onBeforeUnmount, ref } from 'vue';
import { RouterLink } from 'vue-router';
import { createHttpClient } from '../api/http.js';

import AuthFrame from '../components/AuthFrame.vue';
const httpClient = inject('httpClient', createHttpClient());
const invitationCode = ref('');
const username = ref('');
const password = ref('');
const errorMessage = ref('');
const successMessage = ref('');
const submitting = ref(false);

async function submitRegistration() {
  if (submitting.value) return;
  submitting.value = true;
  errorMessage.value = '';
  successMessage.value = '';
  try {
    await httpClient.request('/api/auth/register', {
      method: 'POST',
      body: {
        invitation_code: invitationCode.value,
        username: username.value,
        password: password.value,
      },
    });
    successMessage.value = '注册完成，请使用新账户登录。';
  } catch (error) {
    errorMessage.value = error?.code === 'username_unavailable'
      ? '该用户名暂不可用。'
      : '注册失败，请检查邀请码和输入内容后重试。';
  } finally {
    invitationCode.value = '';
    password.value = '';
    submitting.value = false;
  }
}
onBeforeUnmount(() => { password.value = ''; invitationCode.value = ''; });
</script>

<template>
  <AuthFrame registration>
    <h1 id="register-title">邀请码注册</h1>
    <p class="muted">邀请码仅用于本次注册，不会保存到浏览器。</p>
    <form class="form-stack" @submit.prevent="submitRegistration">
      <label class="field">
        邀请码
        <input
          v-model="invitationCode"
          data-testid="invite-code"
          name="invitation_code"
          type="text"
          autocomplete="off"
          required
        />
      </label>
      <label class="field">
        用户名
        <input v-model="username" data-testid="username" name="username" autocomplete="username" required />
      </label>
      <label class="field">
        密码
        <input v-model="password" data-testid="password" name="password" type="password" autocomplete="new-password" required />
      </label>
      <p v-if="errorMessage" class="form-error" role="alert">{{ errorMessage }}</p>
      <p v-if="successMessage" class="form-success" role="status">{{ successMessage }}</p>
      <button class="primary-button" type="submit" :disabled="submitting">
        {{ submitting ? '正在创建账户…' : '创建账户' }}
      </button>
    </form>
    <div class="inline-links">
      <RouterLink :to="{ name: 'login' }">返回登录</RouterLink>
    </div>
  </AuthFrame>
</template>
