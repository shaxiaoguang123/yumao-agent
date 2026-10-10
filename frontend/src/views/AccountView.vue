<script setup>
import { inject, onBeforeUnmount, ref, watch } from 'vue';
import { RouterLink, useRouter } from 'vue-router';

const sessionStore = inject('sessionStore');
const router = useRouter();
const currentPassword = ref('');
const newPassword = ref('');
const passwordMessage = ref('');
const passwordSubmitting = ref(false);
const passwordSucceeded = ref(false);
let isMounted = true;

function clearPasswords() {
  currentPassword.value = '';
  newPassword.value = '';
}

watch(() => [sessionStore.status, sessionStore.user?.user_id], ([status, userId], [, previousUserId]) => {
  if (status !== 'authenticated' || userId !== previousUserId) clearPasswords();
}, { flush: 'sync' });

async function changePassword() {
  if (!isMounted || passwordSubmitting.value || sessionStore.status !== 'authenticated') return;
  passwordSubmitting.value = true;
  passwordMessage.value = '';
  passwordSucceeded.value = false;
  try {
    const changed = await sessionStore.changePassword(currentPassword.value, newPassword.value);
    if (!isMounted) return;
    passwordSucceeded.value = changed;
    passwordMessage.value = changed
      ? '密码已修改，请重新登录。'
      : sessionStore.errorMessage || '密码修改失败，请检查输入后重试';
  } catch {
    if (isMounted) passwordMessage.value = '密码修改失败，请检查输入后重试';
  } finally {
    if (isMounted) {
      clearPasswords();
      passwordSubmitting.value = false;
    }
  }
}

onBeforeUnmount(() => {
  isMounted = false;
  clearPasswords();
  passwordSubmitting.value = false;
  passwordMessage.value = '';
});

async function logout() {
  const confirmed = await sessionStore.logout();
  if (confirmed) await router.push({ name: 'login' });
}
</script>

<template>
  <section class="panel" aria-labelledby="account-title">
    <template v-if="sessionStore.status === 'unavailable'">
      <h1 id="account-title">暂时无法确认登录状态</h1>
      <p class="muted" role="alert">{{ sessionStore.errorMessage || '请检查连接后重试。' }}</p>
      <button
        data-testid="retry-session"
        class="secondary-button"
        type="button"
        @click="sessionStore.refresh()"
      >
        重试
      </button>
    </template>
    <template v-else>
    <h1 id="account-title">账户设置</h1>
    <p v-if="sessionStore.user" class="muted">当前账户：{{ sessionStore.user.username }}</p>
    <p v-if="passwordMessage" :class="passwordSucceeded ? 'form-success' : 'form-error'" role="status">
      {{ passwordMessage }}
    </p>
    <p v-if="sessionStore.status === 'unauthenticated'" class="muted">
      登录状态已失效。<RouterLink class="action-link" :to="{ name: 'login' }">重新登录</RouterLink>
    </p>

    <form v-if="sessionStore.status === 'authenticated'" class="form-stack" :aria-busy="passwordSubmitting" @submit.prevent="changePassword">
      <h2>修改密码</h2>
      <label class="field">
        当前密码
        <input v-model="currentPassword" type="password" autocomplete="current-password" :disabled="passwordSubmitting" required />
      </label>
      <label class="field">
        新密码
        <input v-model="newPassword" type="password" autocomplete="new-password" minlength="12" :disabled="passwordSubmitting" required />
      </label>
      <p v-if="passwordSubmitting" class="muted" role="status">
        正在修改密码…
      </p>
      <button class="secondary-button" type="submit" :disabled="passwordSubmitting">
        {{ passwordSubmitting ? '正在保存…' : '保存新密码' }}
      </button>
    </form>

    <div v-if="sessionStore.status === 'authenticated'" class="form-stack">
      <h2>登录状态</h2>
      <p v-if="sessionStore.logoutUnconfirmed" role="alert">{{ sessionStore.logoutMessage }}</p>
      <button data-testid="logout" class="primary-button" type="button" :disabled="passwordSubmitting" @click="logout">退出登录</button>
    </div>
    </template>
  </section>
</template>
