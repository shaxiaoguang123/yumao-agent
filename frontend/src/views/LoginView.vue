<script setup>
import { inject, ref } from 'vue';
import { RouterLink, useRouter } from 'vue-router';

const sessionStore = inject('sessionStore');
const router = useRouter();
const username = ref('');
const password = ref('');
const errorMessage = ref('');
const submitting = ref(false);

async function submitLogin() {
  submitting.value = true;
  errorMessage.value = '';
  const accepted = await sessionStore.login(username.value, password.value);
  submitting.value = false;
  if (accepted) {
    password.value = '';
    await router.push({ name: 'home' });
  } else {
    errorMessage.value = sessionStore.errorMessage;
  }
}
</script>

<template>
  <section class="panel" aria-labelledby="login-title">
    <h1 id="login-title">登录</h1>
    <p class="muted">使用你的应用账户进入预约工作台。</p>
    <form class="form-stack" @submit.prevent="submitLogin">
      <label class="field">
        用户名
        <input v-model="username" name="username" autocomplete="username" required />
      </label>
      <label class="field">
        密码
        <input v-model="password" name="password" type="password" autocomplete="current-password" required />
      </label>
      <p v-if="errorMessage" class="form-error" role="alert">{{ errorMessage }}</p>
      <button class="primary-button" type="submit" :disabled="submitting">
        {{ submitting ? '正在登录…' : '登录' }}
      </button>
    </form>
    <div class="inline-links">
      <RouterLink :to="{ name: 'register' }">使用邀请码注册</RouterLink>
    </div>
  </section>
</template>
