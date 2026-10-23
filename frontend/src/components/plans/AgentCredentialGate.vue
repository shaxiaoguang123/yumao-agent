<script setup>
import { computed, onBeforeUnmount, shallowRef, watch } from 'vue';
import { RouterLink } from 'vue-router';

const props = defineProps({
  api: { type: Object, required: true },
  session: { type: Object, required: true },
  credentialId: { type: String, default: '' },
  refreshKey: { type: Number, default: 0 },
});
const emit = defineEmits(['ready-change']);

const state = shallowRef('loading');
const selected = shallowRef(null);
let sequence = 0;
let alive = true;

const isReady = computed(() => state.value === 'ready');
const descriptions = {
  empty: '还没有预约凭据。先添加并验证 Token，再设置支付密码。',
  unselected: '请选择这次预约计划使用的 Token。',
  missing: '所选凭据已不可用，请重新选择。',
  invalid_token: '这个 Token 尚未验证有效、账户绑定未确认、已停用或已过期。',
  missing_password: '这个 Token 尚未设置支付密码。保存意向前请先完成凭据设置。',
  error: '无法读取 Token 和支付密码状态；状态确认前不会发起模型请求。',
};

function tokenIsReady(credential) {
  return credential?.enabled === true
    && credential.last_confirmed_validation_state === 'confirmed_valid'
    && credential.account_binding_state === 'confirmed'
    && credential.requires_revalidation !== true
    && credential.expiry_state !== 'expired';
}

async function load() {
  const current = ++sequence;
  state.value = 'loading';
  selected.value = null;
  emit('ready-change', false);

  if (props.session.status !== 'authenticated' || !props.session.user?.user_id) {
    state.value = 'error';
    return;
  }

  try {
    const result = await props.api.list({ reuse: true });
    if (!alive || current !== sequence) return;
    const credentials = Array.isArray(result?.credentials) ? result.credentials : [];
    if (!credentials.length) {
      state.value = 'empty';
      return;
    }
    const credential = credentials.find(item => item.credential_id === props.credentialId);
    if (!props.credentialId) {
      state.value = 'unselected';
      return;
    }
    if (!credential) {
      state.value = 'missing';
      return;
    }
    selected.value = credential;
    if (!tokenIsReady(credential)) {
      state.value = 'invalid_token';
      return;
    }
    if (credential.has_payment_password !== true) {
      state.value = 'missing_password';
      return;
    }
    state.value = 'ready';
    emit('ready-change', true);
  } catch {
    if (!alive || current !== sequence) return;
    state.value = 'error';
  }
}

watch(
  () => [props.credentialId, props.refreshKey, props.session.status, props.session.user?.user_id, props.session.csrfToken],
  () => { void load(); },
  { immediate: true, flush: 'sync' },
);

onBeforeUnmount(() => {
  alive = false;
  sequence += 1;
});
</script>

<template>
  <section class="agent-credential-gate" :class="{ 'is-ready': isReady, 'is-blocked': !isReady && state !== 'loading' }" aria-label="预约凭据准备状态" aria-live="polite" :data-state="state" data-testid="agent-credential-gate">
    <span class="agent-gate-dot" :class="{ 'is-ready': isReady, 'is-busy': state === 'loading' }" aria-hidden="true" />
    <div class="agent-gate-copy">
      <div class="agent-gate-heading">
        <h3>{{ isReady ? '凭据已就绪' : '凭据状态' }}</h3>
        <span class="agent-gate-status" :class="{ 'is-ready': isReady }">
          {{ state === 'loading' ? '正在核对' : isReady ? '已就绪' : '需要处理' }}
        </span>
      </div>
      <p v-if="state === 'loading'" class="status-loading" role="status">正在读取所选凭据的验证和支付密码状态。</p>
      <p v-else-if="isReady">{{ selected.label }}。可以在右上角切换 Token。</p>
      <p v-else>{{ descriptions[state] }}</p>
      <div v-if="!isReady && state !== 'loading'" class="agent-gate-actions">
        <RouterLink to="/credentials">前往预约凭据设置</RouterLink>
        <button v-if="state === 'error'" class="text-button" type="button" @click="load">重新检查</button>
      </div>
    </div>
  </section>
</template>

<style scoped>
.agent-credential-gate { display: flex; gap:8px; align-items: flex-start; min-width: 0; padding:8px 0; }
.agent-credential-gate.is-ready { align-items: center; padding:8px 0; }
.agent-credential-gate.is-ready .agent-gate-copy p,
.agent-credential-gate.is-ready .agent-gate-status { position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0 0 0 0); }
.agent-gate-dot { flex: none; width: 8px; height: 8px; margin-top:8px; border-radius:50%; background: var(--warning); }
.agent-gate-dot.is-ready { background: var(--success); }
.agent-gate-dot.is-busy { background: var(--brand); }
.agent-gate-copy { min-width: 0; flex: 1; }
.agent-gate-heading { display: flex; align-items: center; flex-wrap: wrap; gap:8px; }
.agent-gate-heading h3 { margin:0; font-size: 15px; font-weight: 600; line-height: 1.4; }
.agent-gate-copy p { margin:8px 0 0; color: var(--muted); font-size: 13px; line-height: 1.5; overflow-wrap: anywhere; }
.agent-gate-status { padding:8px 8px; border-radius:8px; background: var(--warning-soft); color: var(--warning); font-size: 12px; font-weight: 600; }
.agent-gate-status.is-ready { background: var(--success-soft); color: var(--success); }
.agent-gate-actions { display: flex; flex-wrap: wrap; align-items: center; gap:8px; margin-top:8px; }
.agent-gate-actions a, .agent-gate-actions button { min-height:var(--control-height); display: inline-flex; align-items: center; font-size: 15px; font-weight: 600; }
.agent-credential-gate.is-ready { display:inline-flex; align-items:center; gap:5px; padding:0; border:0; background:transparent; }
.agent-credential-gate.is-ready .agent-gate-heading { gap:0; }
.agent-credential-gate.is-ready h3 { font-size:11px; font-weight:400; color:var(--muted); white-space:nowrap; }
.agent-credential-gate.is-ready .agent-gate-status,.agent-credential-gate.is-ready p { display:none; }
</style>
