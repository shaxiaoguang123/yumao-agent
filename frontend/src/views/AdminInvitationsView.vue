<script setup>
import { computed, inject, onBeforeUnmount, ref, watch } from 'vue';
import { RouterLink } from 'vue-router';

import PageHeader from '../components/PageHeader.vue';
import AppIcon from '../components/AppIcon.vue';
const invitationApi = inject('adminInvitationApi');
const sessionStore = inject('sessionStore');
const invitationCode = ref('');
const expiresAtUtcMs = ref(null);
const submitting = ref(false);
const errorMessage = ref('');
const statusMessage = ref('');
const creationOutcomeUncertain = ref(false);
let isMounted = true;
let sessionEpoch = 0;
const isAuthorized = computed(() => (
  sessionStore?.status === 'authenticated' && sessionStore.user?.role === 'admin'
));
const sessionMessage = computed(() => (
  sessionStore?.status === 'unauthenticated'
    ? '登录状态已失效，请重新登录后再试。'
    : '当前无法确认管理员权限，请重新登录后再试。'
));

watch(() => [sessionStore?.status, sessionStore?.user?.user_id, sessionStore?.user?.role], () => {
  // A lost/replaced Session invalidates both plaintext and all in-flight results.
  sessionEpoch += 1;
  dismissInvitation();
}, { flush: 'sync' });

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
    || error?.kind === 'invalid_response'
  ) {
    return '创建结果尚未确认，邀请码可能已经生成。请先确认上次请求未成功，再决定是否重新创建。';
  }
  return '邀请码创建失败，请检查后重试。';
}

async function createInvitation({ acknowledgeUncertainOutcome = false } = {}) {
  if (
    !isMounted
    || !isAuthorized.value
    || !invitationApi
    || submitting.value
    || invitationCode.value
    || (creationOutcomeUncertain.value && !acknowledgeUncertainOutcome)
  ) return;

  creationOutcomeUncertain.value = false;
  submitting.value = true;
  errorMessage.value = '';
  statusMessage.value = '';
  const requestEpoch = sessionEpoch;
  try {
    const result = await invitationApi.create();
    if (!isMounted || !isAuthorized.value || requestEpoch !== sessionEpoch) return;
    invitationCode.value = result.invitation_code;
    expiresAtUtcMs.value = result.expires_at_utc_ms;
  } catch (error) {
    if (!isMounted || !isAuthorized.value || requestEpoch !== sessionEpoch) return;
    errorMessage.value = safeErrorMessage(error);
    creationOutcomeUncertain.value = (
      error?.status >= 500
      || error?.kind === 'network'
      || error?.kind === 'timeout'
      || error?.kind === 'invalid_response'
    );
  } finally {
    if (isMounted && requestEpoch === sessionEpoch) submitting.value = false;
  }
}

function createAnotherAfterUncertainOutcome() {
  if (!isAuthorized.value || !creationOutcomeUncertain.value || submitting.value) return;
  const confirmed = window.confirm(
    '上次请求可能已经创建邀请码，但当前无法查看结果。继续会再创建一个新邀请码，可能留下未使用的邀请码。仍要继续吗？',
  );
  if (!confirmed) return;
  return createInvitation({ acknowledgeUncertainOutcome: true });
}

async function copyInvitation() {
  if (!isAuthorized.value || !invitationCode.value) return;
  const copyEpoch = sessionEpoch;
  statusMessage.value = '';
  try {
    if (!navigator.clipboard?.writeText) throw new Error('clipboard_unavailable');
    await navigator.clipboard.writeText(invitationCode.value);
    if (isMounted && isAuthorized.value && copyEpoch === sessionEpoch) statusMessage.value = '邀请码已复制。';
  } catch {
    if (isMounted && isAuthorized.value && copyEpoch === sessionEpoch) statusMessage.value = '复制失败，请手动选择并复制邀请码。';
  }
}

function dismissInvitation() {
  invitationCode.value = '';
  expiresAtUtcMs.value = null;
  submitting.value = false;
  creationOutcomeUncertain.value = false;
  statusMessage.value = '';
  errorMessage.value = '';
}

onBeforeUnmount(() => {
  isMounted = false;
  sessionEpoch += 1;
  dismissInvitation();
});
</script>

<template>
  <section class="admin-page" aria-labelledby="admin-invitations-title">
    <PageHeader title-id="admin-invitations-title" eyebrow="管理员工具" title="创建注册邀请码" description="为受邀用户提供安全的账户入口。邀请码明文只临时显示一次。" />
    <div class="admin-grid"><div class="panel admin-invitations-panel"><span class="section-icon"><AppIcon name="ticket" /></span><h2 class="invitation-create-heading">新建邀请码</h2>
    <p class="muted">
      邀请码有效期为 24 小时，且只能注册一个账户。创建后请立即复制并安全地交给受邀用户。
      邀请码只在本页临时显示一次。
    </p>

    <p v-if="!isAuthorized" class="form-error" role="alert">
      {{ sessionMessage }} <RouterLink class="action-link" :to="{ name: 'login' }">重新登录</RouterLink>
    </p>

    <form class="form-stack" @submit.prevent="createInvitation">
      <p v-if="errorMessage" class="form-error" role="alert">{{ errorMessage }}</p>
      <button
        data-testid="create-invitation"
        class="primary-button"
        type="submit"
        :disabled="!isAuthorized || submitting || Boolean(invitationCode) || creationOutcomeUncertain || !invitationApi"
      >
        {{ submitting ? '正在创建…' : '创建邀请码' }}
      </button>
      <p v-if="creationOutcomeUncertain" class="uncertain-create-warning" role="alert">
        页面不会自动重试。确认上次结果未知、且仍要创建另一个邀请码时，再使用下面的操作。
      </p>
      <button
        v-if="creationOutcomeUncertain"
        data-testid="confirm-create-after-uncertain"
        class="secondary-button"
        type="button"
        :disabled="!isAuthorized || submitting"
        @click="createAnotherAfterUncertainOutcome"
      >
        我理解可能已有邀请码，仍要创建另一个
      </button>
    </form>

    <section
      v-if="isAuthorized && invitationCode"
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

    <RouterLink class="action-link back-link" :to="{ name: 'home' }">返回首页</RouterLink>
    </div><aside class="invitation-guide"><p class="eyebrow">邀请流程</p><h2>一个入口，三步完成</h2><ol><li><strong>创建</strong><span>管理员创建一个有效期为 24 小时的邀请码。</span></li><li><strong>安全分享</strong><span>复制后，通过可信渠道交给受邀用户。离开页面后无法再次查看明文。</span></li><li><strong>完成注册</strong><span>受邀用户填写邀请码、用户名与密码。一个邀请码仅注册一个账户。</span></li></ol><p class="security-caption"><AppIcon name="shield" />页面不会自动重试创建请求。</p></aside></div>
  </section>
</template>

<style scoped>
.admin-grid {
  display:grid;
  grid-template-columns:minmax(0,1.3fr) minmax(0,1fr);
  gap:30px;
  align-items:start;

}

.admin-invitations-panel > .muted {
  font-size:13px;

}

.invitation-create-heading {
  margin-top:18px;

}

.invitation-guide {
  padding:22px 8px;

}

.invitation-guide h2 {
  font-size:20px;

}

.invitation-guide ol {
  padding:0;
  margin:26px 0 30px;
  list-style:none;
  counter-reset:steps;
  display:grid;
  gap:25px;

}

.invitation-guide li {
  position:relative;
  padding-left:44px;
  counter-increment:steps;

}

.invitation-guide li:before {
  content:"0" counter(steps);
  position:absolute;
  top:0;
  left:0;
  width:29px;
  height:29px;
  display:grid;
  place-items:center;
  border:1px solid var(--line);
  border-radius:7px;
  color:var(--brand);
  background:white;
  font-size:10px;

}

.invitation-guide strong {
  display:block;
  font-size:13px;
  margin-bottom:8px;

}

.invitation-guide li span {
  display:block;
  font-size:12px;
  color:var(--muted);
  line-height:1.8;

}

.invitation-result {
  display:grid;
  gap:13px;
  padding:20px;
  margin-top:24px;
  background:var(--brand-soft);
  border:1px solid #cbded0;
  border-radius:12px;

}

.invitation-result h2 {
  font-size:18px;

}

.invitation-result .muted {
  margin:0;
  font-size:12px;

}

.invitation-code {
  display:block;
  overflow-wrap:anywhere;
  padding:16px;
  border:1px dashed #b5ceb9;
  background:white;
  border-radius:8px;
  color:var(--brand-dark);
  font-family:ui-monospace,SFMono-Regular,monospace;
  font-size:16px;
  line-height:1.8;
  user-select:all;

}

.expiry-line {
  margin:0;
  color:var(--muted);
  font-size:12px;

}

.invitation-actions {
  display:flex;
  flex-wrap:wrap;
  gap:8px;

}

.copy-status {
  margin:0;
  font-size:12px;
  color:var(--brand);

}

.uncertain-create-warning {
  padding:12px 15px;
  color:var(--warning);
  background:var(--warning-soft);
  border-radius:9px;
  margin:0;
  line-height:1.8;
  font-size:12px;

}

.back-link {
  margin-top:18px;

} @media(max-width:700px) {
  .admin-grid {
  grid-template-columns:1fr;
  gap:12px;

}

.invitation-guide {
  padding:20px 8px;

}
}
</style>
