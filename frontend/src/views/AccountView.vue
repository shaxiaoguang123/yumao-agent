<script setup>
import { inject, ref } from 'vue';
import { useRouter } from 'vue-router';

const sessionStore = inject('sessionStore');
const router = useRouter();
const currentPassword = ref('');
const newPassword = ref('');
const passwordMessage = ref('');

async function changePassword() {
  passwordMessage.value = '';
  const changed = await sessionStore.changePassword(
    currentPassword.value,
    newPassword.value,
  );
  if (changed) {
    passwordMessage.value = '密码已修改，请重新登录。';
  } else {
    passwordMessage.value = sessionStore.errorMessage;
  }
  currentPassword.value = '';
  newPassword.value = '';
}

async function logout() {
  const confirmed = await sessionStore.logout();
  if (confirmed) await router.push({ name: 'login' });
}
</script>

<template>
  <section class="panel" aria-labelledby="account-title">
    <h1 id="account-title">账户设置</h1>
    <p class="muted">当前账户：{{ sessionStore.user?.username }}</p>

    <form class="form-stack" @submit.prevent="changePassword">
      <h2>修改密码</h2>
      <label class="field">
        当前密码
        <input v-model="currentPassword" type="password" autocomplete="current-password" required />
      </label>
      <label class="field">
        新密码
        <input v-model="newPassword" type="password" autocomplete="new-password" minlength="12" required />
      </label>
      <p v-if="passwordMessage" :class="sessionStore.status === 'authenticated' ? 'form-error' : 'form-success'" role="status">
        {{ passwordMessage }}
      </p>
      <button class="secondary-button" type="submit">保存新密码</button>
    </form>

    <div class="form-stack">
      <h2>登录状态</h2>
      <p v-if="sessionStore.logoutUnconfirmed" role="alert">{{ sessionStore.logoutMessage }}</p>
      <button data-testid="logout" class="primary-button" type="button" @click="logout">退出登录</button>
    </div>
  </section>
</template>
