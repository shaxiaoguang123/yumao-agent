<script setup>
import { computed, inject, onBeforeUnmount, ref } from 'vue';
import { RouterLink } from 'vue-router';

const invitationApi = inject('adminInvitationApi');
const invitationCode = ref('');
const expiresAtUtcMs = ref(null);
const submitting = ref(false);
const errorMessage = ref('');
const statusMessage = ref('');

const expiryIso = computed(() => (
  expiresAtUtcMs.value === null
    ? ''
    : new Date(expiresAtUtcMs.value).toISOString()
));
const expiryLabel = computed(() => (
  expiresAtUtcMs.value === null
    ? ''
    : new Intl.DateTimeFormat('zh-CN', {
      dateStyle: 'medium',
      timeStyle: 'short',
    }).format(new Date(expiresAtUtcMs.value))
));

function safeErrorMessage(error) {
  if (error?.sessionInvalid || error?.status === 401) {
    return '登录状态已失效，请重新登录后再试。';
  }
  if (error?.status === 403) {
    return '当前会话没有管理员权限，或请求校验未通过。';
  }
  if (error?.status === 409) {
    return '创建请求发生冲突，请检查当前页面状态后再试。';
  }
  if (error?.status === 429) {
    return '操作过于频繁，请稍后再试。';
  }
  if (
    error?.status >= 500
    || error?.kind === 'network'
    || error?.kind === 'timeout'
  ) {
    return '创建结果尚未确认，邀请码可能已经生成。请先确认上次请求未成功，再决定是否重新创建。';
  }
  return '邀请码创建失败，请检查后重试。';
}

async function createInvitation() {
  if (submitting.value || invitationCode.value) return;

  submitting.value = true;
  errorMessage.value = '';
  statusMessage.value = '';
  try {
    const result = await invitationApi.create();
    invitationCode.value = result.invitation_code;
    expiresAtUtcMs.value = result.expires_at_utc_ms;
  } catch (error) {
    errorMessage.value = safeErrorMessage(error);
  } finally {
    submitting.value = false;
  }
}

async function copyInvitation() {
  if (!invitationCode.value) return;
  statusMessage.value = '';
  try {
    if (!navigator.clipboard?.writeText) throw new Error('clipboard_unavailable');
    await navigator.clipboard.writeText(invitationCode.value);
    statusMessage.value = '邀请码已复制。';
  } catch {
    statusMessage.value = '复制失败，请手动选择并复制邀请码。';
  }
}

function dismissInvitation() {
  invitationCode.value = '';
  expiresAtUtcMs.value = null;
  statusMessage.value = '';
  errorMessage.value = '';
}

onBeforeUnmount(dismissInvitation);
</script>

<template>
  <section class="panel admin-invitations-panel" aria-labelledby="admin-invitations-title">
    <p class="eyebrow">管理员</p>
    <h1 id="admin-invitations-title">创建注册邀请码</h1>
    <p class="muted">
      邀请码有效期为 24 小时，且只能注册一个账户。创建后请立即复制并安全地交给受邀用户。
      邀请码只在本页临时显示一次。
    </p>

    <form class="form-stack" @submit.prevent="createInvitation">
      <p v-if="errorMessage" class="form-error" role="alert">{{ errorMessage }}</p>
      <button
        data-testid="create-invitation"
        class="primary-button"
        type="submit"
        :disabled="submitting || Boolean(invitationCode) || !invitationApi"
      >
        {{ submitting ? '正在创建…' : '创建邀请码' }}
      </button>
    </form>

    <section
      v-if="invitationCode"
      class="invitation-result"
      aria-labelledby="invitation-result-title"
      aria-live="polite"
    >
      <h2 id="invitation-result-title">邀请码已创建</h2>
      <p class="muted">请现在复制。离开或关闭本页后无法再次查看这段明文。</p>
      <code data-testid="invitation-code" class="invitation-code">{{ invitationCode }}</code>
      <p class="expiry-line">
        有效期至
        <time data-testid="invitation-expiry" :datetime="expiryIso">{{ expiryLabel }}</time>
      </p>
      <div class="invitation-actions">
        <button
          data-testid="copy-invitation"
          class="primary-button"
          type="button"
          @click="copyInvitation"
        >
          复制邀请码
        </button>
        <button
          data-testid="dismiss-invitation"
          class="secondary-button"
          type="button"
          @click="dismissInvitation"
        >
          已妥善保存，关闭显示
        </button>
      </div>
      <p v-if="statusMessage" class="copy-status" role="status">{{ statusMessage }}</p>
    </section>

    <RouterLink class="back-link" :to="{ name: 'home' }">返回首页</RouterLink>
  </section>
</template>

<style scoped>
.admin-invitations-panel { width: min(100%, 42rem); }
.eyebrow { margin: 0 0 .5rem; color: #146c5b; font-size: .82rem; font-weight: 750; letter-spacing: .06em; text-transform: uppercase; }
.admin-invitations-panel h1 { margin-bottom: .5rem; }
.invitation-result { display: grid; gap: .75rem; margin-top: 1.5rem; padding: 1.25rem; border: 1px solid #cfe3dc; border-radius: .8rem; background: #f5fbf8; }
.invitation-result h2 { margin: 0; font-size: 1.1rem; }
.invitation-result .muted { margin: 0; }
.invitation-code { overflow-wrap: anywhere; padding: .9rem; border: 1px solid #d9e4df; border-radius: .55rem; background: white; color: #163b35; font-size: 1rem; user-select: all; }
.expiry-line { margin: 0; color: #334155; font-size: .9rem; }
.invitation-actions { display: flex; flex-wrap: wrap; gap: .65rem; }
.copy-status { margin: 0; color: #176348; font-size: .9rem; }
.back-link { display: inline-block; margin-top: 1.25rem; }
</style>
