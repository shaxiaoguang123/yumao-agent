<script setup>
import { inject, onBeforeUnmount, ref, watch } from 'vue';
import { RouterLink, useRouter } from 'vue-router';

import PageHeader from '../components/PageHeader.vue';
import AppIcon from '../components/AppIcon.vue';
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
  <section class="account-page" aria-labelledby="account-title">
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
    <PageHeader title-id="account-title" title="账户设置" />
    <div v-if="sessionStore.user" class="account-identity"><span class="section-icon"><AppIcon name="user" /></span><div><span class="eyebrow">当前账户</span><p>{{ sessionStore.user.username }}</p></div><span class="state-pill state-enabled">{{ sessionStore.user.role === 'admin' ? '管理员' : '用户' }}</span></div>
    <p v-if="passwordMessage" :class="passwordSucceeded ? 'form-success' : 'form-error'" role="status">
      {{ passwordMessage }}
    </p>
    <p v-if="sessionStore.status === 'unauthenticated'" class="muted">
      登录状态已失效。<RouterLink class="action-link" :to="{ name: 'login' }">重新登录</RouterLink>
    </p>

    <div class="account-grid">
    <form v-if="sessionStore.status === 'authenticated'" class="form-stack panel account-password" :aria-busy="passwordSubmitting" @submit.prevent="changePassword">
      <h2>修改密码</h2><p class="muted account-section-description">修改成功后需重新登录。</p>
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
      <button class="primary-button" type="submit" :disabled="passwordSubmitting">
        {{ passwordSubmitting ? '正在保存…' : '保存新密码' }}
      </button>
    </form>

    <div v-if="sessionStore.status === 'authenticated'" class="form-stack panel account-session">
      <h2>当前会话</h2>
      <p v-if="sessionStore.logoutUnconfirmed" role="alert">{{ sessionStore.logoutMessage }}</p>
      <button data-testid="logout" class="secondary-button" type="button" :disabled="passwordSubmitting" @click="logout">退出登录</button>
    </div>
    </div>
    </template>
  </section>
</template>

<style scoped>
.account-page { max-width:760px; margin:0 auto; }
.account-identity { display:flex; align-items:center; gap:12px; margin:0 0 16px; }
.account-identity > div { min-width:0; flex:1; }
.account-identity p { margin:2px 0 0; font-size:15px; font-weight:600; }
.account-identity .eyebrow { font-size:12px; }
.account-grid { display:grid; grid-template-columns:minmax(0,1fr); gap:12px; }
.account-grid .form-stack { margin:0; }
.account-password { grid-template-columns:repeat(2,minmax(0,1fr)); gap:16px; }
.account-password h2,.account-section-description,.account-password > p[role] { grid-column:1/-1; }
.account-section-description { margin:-8px 0 0; color:var(--muted); font-size:13px; }
.account-password > button { justify-self:start; }
.account-session { display:flex; flex-wrap:wrap; align-items:center; justify-content:space-between; gap:12px; box-shadow:none; }
.account-session h2 { font-size:14px; }
.account-session > p { flex-basis:100%; }
.account-session > button { margin-left:auto; }
@media(max-width:600px) { .account-password { grid-template-columns:minmax(0,1fr); gap:12px; } }
</style>
