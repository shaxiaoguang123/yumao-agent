<script setup>
import { computed, inject, onMounted, onUnmounted, ref, watch } from 'vue';
import { onBeforeRouteLeave, useRoute, useRouter } from 'vue-router';

import PageHeader from '../components/PageHeader.vue';
import AppIcon from '../components/AppIcon.vue';
import CredentialCard from '../components/CredentialCard.vue';
import { needsAttention } from '../utils/credentialSummary.js';
import { planSetupRequirement } from '../utils/credentialReadiness.js';
const api = inject('credentialApi');
const route = useRoute();
const router = useRouter();
const credentials = ref([]);
const listStatus = ref('loading');
const loading = computed(() => listStatus.value === 'loading');
let listRequestId = 0;
const loadingError = ref('');
const errorMessage = ref('');
const successMessage = ref('');
const creating = ref(false);
const busyCredentialId = ref('');
const search = ref('');
const filter = ref('all');
const label = ref('');
const createToken = ref('');
const createPaymentPassword = ref('');
const rotationCredentialId = ref('');
const rotationToken = ref('');
const paymentPasswordCredentialId = ref('');
const paymentPassword = ref('');
const visibleCredentials = computed(() => credentials.value.filter(item => (
 item.label.toLocaleLowerCase().includes(search.value.trim().toLocaleLowerCase())
 && (filter.value === 'all' || (filter.value === 'enabled' && item.enabled) || (filter.value === 'disabled' && !item.enabled) || (filter.value === 'attention' && needsAttention(item)))
)));
const planSetupNotice = computed(() => {
  if (route.query.returnTo !== 'plans') return '';
  if (route.query.setup === 'token') return '预约计划需要至少一个已验证且有效的 Token，并设置支付密码。请先完成凭据设置。';
  if (route.query.setup === 'payment_password') return '已找到有效 Token，但还没有支付密码。设置完成后会返回预约计划。';
  if (route.query.setup === 'check_failed') return '暂时无法确认预约准备状态；这不代表 Token 无效。请重试读取凭据。';
  return '';
});

async function returnToPlansIfReady() {
  if (route.query.returnTo !== 'plans' || planSetupRequirement(credentials.value)) return;
  await router.replace({ name: 'plans' });
}
// A hidden card must not retain a rotation candidate that can reappear later.
watch([search, filter], () => {
  if (rotationCredentialId.value && !visibleCredentials.value.some(item => item.credential_id === rotationCredentialId.value)) {
    rotationToken.value = '';
    rotationCredentialId.value = '';
  }
  if (paymentPasswordCredentialId.value && !visibleCredentials.value.some(item => item.credential_id === paymentPasswordCredentialId.value)) {
    paymentPassword.value = '';
    paymentPasswordCredentialId.value = '';
  }
}, { flush: 'sync' });

const safeErrors = {
  invalid_request: '输入内容无效，请检查后重试。',
  invalid_credential_label: '名称长度须为 1 到 128 个字符，且不能包含控制字符。',
  invalid_credential_token: 'Token 格式无效，请重新输入。',
  invalid_credential_enabled: '凭据启用状态无效，请刷新后重试。',
  invalid_credential_version: '凭据版本无效，请刷新凭据列表后重试。',
  invalid_payment_password: '支付密码格式无效，请检查后重试。',
  invalid_user: '登录用户状态无效，请重新登录后重试。',
  credential_token_expired: '此 Token 已过期，请替换 Token。',
  credential_token_invalid: '此 Token 已确认无效，请替换 Token。',
  credential_account_already_configured: '此上游账户已绑定到本用户的其他凭据，请重新启用或轮换已有凭据。',
  credential_account_binding_unresolved: '账户连续性尚未确认；请先验证现有凭据或删除后重新添加。',
  credential_account_reconfirmation_required: '账户连续性需要重新确认；当前凭据不能轮换。',
  credential_account_mismatch: '替换 Token 与当前账户不匹配，原凭据保持不变。',
  credential_version_conflict: '凭据已更新，请刷新后重试。',
  credential_requires_revalidation: '凭据状态需要重新验证；请先重新验证 Token 后再操作。',
  credential_write_failed: '服务器未能保存凭据。请刷新凭据列表确认结果后，再决定是否重试。',
  credential_update_failed: '服务器未能更新凭据。请刷新凭据列表确认当前状态后重试。',
  credential_delete_failed: '服务器未能确认删除结果。请刷新凭据列表核对后再操作。',
  credential_validation_write_failed: '验证结果暂未写入。请刷新凭据状态后重新验证。',
  credential_rotation_write_failed: 'Token 轮换结果暂未确认。请刷新凭据并核对当前 Token 状态后重试。',
  credential_secret_unavailable: '凭据密钥暂不可用，请检查服务端加密配置后重试。',
  credential_snapshot_unavailable: '凭据状态暂时无法读取，请刷新后重试。',
  credential_fingerprint_key_unavailable: '凭据校验暂不可用，请检查服务端密钥配置。',
  upstream_read_failed: '上游 Token 验证未完成，凭据未标记为有效；请检查 Token 状态后重试。',
  validation_stale: '验证结果已过期，凭据状态未被覆盖。请重新加载后再试。',
  validation_rate_limited: '上游请求暂时受到限流，请稍后重试。',
  validation_not_configured: '上游验证尚未配置，Token 未保存。',
  upstream_rate_limited: '上游请求暂时受到限流，请稍后重试。',
  upstream_unavailable: '上游服务暂时不可用，请稍后重试。',
  upstream_contract_drift: '上游协议发生变化，验证已暂停。',
  upstream_validation_unknown: '上游验证暂不可用，请稍后重试。',
  credential_disabled: '此凭据已停用，请先重新启用。',
  credential_not_found: '找不到此凭据，请刷新列表。',
};

function safeMessage(error, { mutation = false } = {}) {
  if (safeErrors[error?.code]) return safeErrors[error.code];
  if (error?.message === 'invalid_response') return '凭据服务返回的数据格式异常，请重新读取。';
  if (error?.kind === 'network') {
    return mutation
      ? '与凭据服务的连接中断，本次操作结果未确认。请先刷新凭据列表核对，再决定是否重试。'
      : '无法连接凭据服务，请确认本地服务正在运行后重新读取。';
  }
  if (error?.kind === 'timeout') {
    return mutation
      ? '凭据操作等待超时，结果未确认。请先刷新凭据列表核对，再决定是否重试。'
      : '读取凭据超时，请稍后刷新重试。';
  }
  if (typeof error?.code === 'string' && /^[a-z0-9][a-z0-9_-]{0,63}$/i.test(error.code)) {
    return `服务端返回错误码 ${error.code}。${mutation ? '请先刷新凭据列表核对当前状态，再决定是否重试。' : '请重新读取后重试。'}`;
  }
  if (error?.status >= 500) {
    return mutation
      ? `凭据服务暂时异常（HTTP ${error.status}），操作结果未确认。请先刷新列表核对，再决定是否重试。`
      : `凭据服务暂时异常（HTTP ${error.status}），请稍后重新读取。`;
  }
  if (error?.status === 409) return '凭据状态已变化，请刷新列表后重试。';
  return mutation
    ? '凭据服务未确认本次操作。请先刷新列表核对状态，再决定是否重试。'
    : '无法读取凭据状态，请重试。';
}

async function loadCredentials() {
  const requestId = ++listRequestId;
  listStatus.value = 'loading';
  loadingError.value = '';
  try {
    const result = await api.list();
    if (requestId !== listRequestId) return;
    if (!Array.isArray(result?.credentials)) throw new Error('invalid_response');
    credentials.value = result.credentials;
    listStatus.value = 'ready';
    await returnToPlansIfReady();
  } catch (error) {
    if (requestId !== listRequestId) return;
    loadingError.value = safeMessage(error);
    listStatus.value = 'error';
  }
}

function clearSensitiveInputs() {
  createToken.value = '';
  createPaymentPassword.value = '';
  rotationToken.value = '';
  rotationCredentialId.value = '';
  paymentPassword.value = '';
  paymentPasswordCredentialId.value = '';
}

function cancelCreate() {
  label.value = '';
  createToken.value = '';
  createPaymentPassword.value = '';
  errorMessage.value = '';
}

function beginRotation(credentialId) {
  errorMessage.value = '';
  paymentPasswordCredentialId.value = '';
  paymentPassword.value = '';
  rotationCredentialId.value = credentialId;
  rotationToken.value = '';
}

function beginPaymentPassword(credentialId) {
  errorMessage.value = '';
  rotationCredentialId.value = '';
  rotationToken.value = '';
  paymentPasswordCredentialId.value = credentialId;
  paymentPassword.value = '';
}

function cancelRotation() {
  rotationToken.value = '';
  rotationCredentialId.value = '';
  paymentPassword.value = '';
  paymentPasswordCredentialId.value = '';
  errorMessage.value = '';
}

async function createCredential() {
  if (creating.value) return;
  creating.value = true;
  errorMessage.value = '';
  successMessage.value = '';
  const submittedLabel = label.value;
  const submittedToken = createToken.value;
  const submittedPaymentPassword = createPaymentPassword.value;
  if (!submittedPaymentPassword) {
    errorMessage.value = safeMessage({ code: 'invalid_payment_password' });
    creating.value = false;
    return;
  }
  try {
    await api.create({ label: submittedLabel, token: submittedToken, payment_password: submittedPaymentPassword });
    label.value = '';
    successMessage.value = '凭据已添加。';
    await loadCredentials();
  } catch (error) {
    errorMessage.value = safeMessage(error, { mutation: true });
  } finally {
    createToken.value = '';
    createPaymentPassword.value = '';
    creating.value = false;
  }
}

async function savePaymentPassword(credential) {
  if (busyCredentialId.value || !paymentPassword.value) return;
  busyCredentialId.value = credential.credential_id;
  errorMessage.value = '';
  successMessage.value = '';
  try {
    await api.setPaymentPassword(credential.credential_id, paymentPassword.value, credential.credential_version);
    successMessage.value = '支付密码已单独加密保存；此操作没有发起支付。';
    paymentPasswordCredentialId.value = '';
  } catch (error) {
    errorMessage.value = safeMessage(error, { mutation: true });
  } finally {
    paymentPassword.value = '';
    busyCredentialId.value = '';
    await loadCredentials();
  }
}

async function runCredentialAction(credential, action, successText) {
  if (busyCredentialId.value) return;
  busyCredentialId.value = credential.credential_id;
  errorMessage.value = '';
  successMessage.value = '';
  try {
    await action();
    successMessage.value = successText;
  } catch (error) {
    errorMessage.value = safeMessage(error, { mutation: true });
  } finally {
    busyCredentialId.value = '';
    await loadCredentials();
  }
}

function validateCredential(credential) {
  return runCredentialAction(
    credential,
    () => api.validate(
      credential.credential_id,
      credential.credential_version,
      credential.current_token_revision_id,
    ),
    '验证请求已完成。',
  );
}

function toggleEnabled(credential) {
  return runCredentialAction(
    credential,
    () => api.update(credential.credential_id, {
      expected_credential_version: credential.credential_version,
      enabled: !credential.enabled,
    }),
    credential.enabled ? '凭据已停用。' : '凭据已启用；请重新验证当前 Token。',
  );
}

function deleteCredential(credential) {
  const confirmed = window.confirm(
    `确认删除“${credential.label}”吗？已保存的 Token 和支付密码都会被清除，且此操作无法撤销。`,
  );
  if (!confirmed) return;

  return runCredentialAction(
    credential,
    () => api.remove(credential.credential_id, credential.credential_version),
    '凭据已删除。',
  );
}

async function rotateCredential(credential) {
  if (busyCredentialId.value) return;
  busyCredentialId.value = credential.credential_id;
  errorMessage.value = '';
  successMessage.value = '';
  const submittedToken = rotationToken.value;
  try {
    await api.rotateToken(
      credential.credential_id,
      submittedToken,
      credential.credential_version,
      credential.current_token_revision_id,
    );
    rotationCredentialId.value = '';
    successMessage.value = 'Token 已轮换。';
  } catch (error) {
    errorMessage.value = safeMessage(error, { mutation: true });
  } finally {
    rotationToken.value = '';
    busyCredentialId.value = '';
    await loadCredentials();
  }
}

onMounted(() => loadCredentials());
onBeforeRouteLeave(() => clearSensitiveInputs());
onUnmounted(() => {
  listRequestId += 1;
  clearSensitiveInputs();
});
</script>

<template>
  <section class="credential-page" aria-labelledby="credential-title">
    <PageHeader title-id="credential-title" eyebrow="账户安全 · 凭据管理" title="预约凭据" />

    <p v-if="planSetupNotice" class="credential-message error-message" role="alert">
      {{ planSetupNotice }}
      <button v-if="route.query.setup === 'check_failed'" class="text-button" type="button" @click="loadCredentials">重试
      </button>
    </p>
    <p v-if="errorMessage" class="credential-message error-message" role="alert">
      {{ errorMessage }}
    </p>
    <p v-if="successMessage" class="credential-message success-message" role="status">
      {{ successMessage }}
    </p>
    <p v-if="loadingError" class="credential-message error-message" role="alert">
      未能读取凭据列表。{{ loadingError }}
      <button class="text-button" type="button" @click="loadCredentials()">重试</button>
    </p>

    <div class="credential-workspace">
    <section class="credential-add panel" aria-labelledby="credential-add-title">
      <header class="credential-add-heading">
        <span class="section-icon"><AppIcon name="plus" /></span>
        <div><h2 id="credential-add-title">添加预约凭据</h2><p class="muted">Token 验证后加密保存；支付密码单独加密保存，不参与 Token 验证。</p></div>
      </header>
      <form class="credential-create-grid" data-testid="credential-create" @submit.prevent="createCredential">
        <label class="field">凭据名称<input v-model="label" data-testid="credential-label" type="text" maxlength="128" autocomplete="off" required /></label>
        <label class="field">上游 Token<input v-model="createToken" data-testid="credential-token" type="password" autocomplete="off" spellcheck="false" required /></label>
        <label class="field">支付密码<input v-model="createPaymentPassword" data-testid="credential-payment-password" type="password" autocomplete="new-password" required /><small>单独加密保存；非空抢票队列授权付款，执行器启用后才会执行。</small></label>
        <div class="credential-actions"><button class="primary-button" type="submit" :disabled="creating">{{ creating ? '验证并保存中…' : '验证并保存凭据' }}</button><button class="secondary-button" type="button" data-testid="credential-create-cancel" @click="cancelCreate">清空</button></div>
      </form>
    </section>

    <section class="credential-list" aria-labelledby="credential-list-title" :aria-busy="loading">
      <div class="section-heading">
        <h2 id="credential-list-title">已保存凭据</h2>
        <button class="text-button" type="button" :disabled="loading" @click="loadCredentials()">
          刷新
        </button>
      </div>
      <div v-if="listStatus === 'ready' && credentials.length" class="credential-toolbar">
       <label class="search-field"><AppIcon name="search" /><span class="sr-only">搜索凭据名称</span><input v-model="search" data-testid="credential-search" type="search" placeholder="搜索凭据名称" autocomplete="off" /></label>
       <label class="filter-field"><span class="sr-only">凭据状态</span><select v-model="filter" data-testid="credential-filter" aria-label="凭据状态"><option value="all">全部状态</option><option value="attention">需要关注</option><option value="enabled">已启用</option><option value="disabled">已停用</option></select></label>
      </div>
      <p v-if="listStatus === 'ready' && credentials.length && !visibleCredentials.length" class="search-empty">没有匹配的凭据。请调整名称或状态筛选。</p>
      <p v-if="loading" class="muted" role="status">正在读取凭据状态…</p>
      <p v-else-if="listStatus === 'ready' && credentials.length === 0" class="empty-state">
        暂无预约凭据。添加后可查看 Token 状态和账户连续性。
      </p>

      <div v-if="listStatus === 'ready' && visibleCredentials.length" class="credential-cards">
      <CredentialCard v-for="credential in visibleCredentials" :key="credential.credential_id" :credential="credential" :busy="Boolean(busyCredentialId)" @validate="validateCredential(credential)" @rotate="beginRotation(credential.credential_id)" @payment-password="beginPaymentPassword(credential.credential_id)" @toggle="toggleEnabled(credential)" @remove="deleteCredential(credential)">
        <form
          v-if="rotationCredentialId === credential.credential_id"
          class="rotation-form"
          data-testid="rotation-form"
          @submit.prevent="rotateCredential(credential)"
        >
          <label class="field">
            新 Token
            <input
              v-model="rotationToken"
              data-testid="rotation-token"
              type="password"
              autocomplete="off"
              spellcheck="false"
              required
            />
          </label>
          <div class="credential-actions">
            <button
              class="primary-button"
              type="submit"
              data-testid="rotation-submit"
              :disabled="busyCredentialId === credential.credential_id"
            >
              验证并轮换
            </button>
            <button
              class="secondary-button"
              type="button"
              data-testid="rotation-cancel"
              @click="cancelRotation"
            >
              取消
            </button>
          </div>
        </form>
        <form v-if="paymentPasswordCredentialId === credential.credential_id" class="rotation-form payment-password-form" :data-testid="`payment-password-form-${credential.credential_id}`" @submit.prevent="savePaymentPassword(credential)">
          <label class="field">{{ credential.has_payment_password ? '新支付密码' : '支付密码' }}<input v-model="paymentPassword" type="password" autocomplete="new-password" data-testid="payment-password-input" required /></label>
          <p class="muted">保存后由服务器单独加密保管；此 Token 有非空抢票队列且执行器启用时，系统会读取该密码完成付款。</p>
          <div class="credential-actions"><button class="primary-button" type="submit" :disabled="busyCredentialId === credential.credential_id">加密保存</button><button class="secondary-button" type="button" data-testid="payment-password-cancel" @click="cancelRotation">取消</button></div>
        </form>
      </CredentialCard>
      </div>
    </section>
    </div>
  </section>
</template>

<style scoped>
.credential-message {
  margin:0 0 16px;

}

.credential-workspace {
  display:grid;
  grid-template-columns:minmax(0,1fr);
  gap:16px;
  align-items:start;

}

.credential-add{padding:16px;min-width:0}.credential-add-heading{display:flex;align-items:flex-start;gap:8px;margin-bottom:16px}.credential-add-heading .section-icon{flex:0 0 40px;height:40px;display:grid;place-items:center;border:1px solid var(--line);border-radius:8px;background:var(--brand-soft);color:var(--brand)}.credential-add-heading h2{font-size:17px;margin:0}.credential-add-heading p{font-size:12px;line-height:1.6;margin:8px 0 0}.credential-create-grid{display:grid;gap:16px}.credential-create-grid .field{min-width:0}.credential-create-grid .field input{min-width:0;width:100%}.credential-create-grid .field small{font-size:11px;color:var(--muted);line-height:1.5}.credential-create-grid button{min-height:var(--control-height);font-size:12px}.credential-create-grid .credential-actions{margin-top:8px}

.credential-actions {
  display:flex;
  flex-wrap:wrap;
  gap:8px;

}

.credential-list {
  display:grid;
  grid-template-columns:minmax(0,1fr);
  gap:16px;
  min-width:0;

}
.credential-cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,320px),1fr));gap:8px;align-items:start;min-width:0}.credential-cards :deep(.credential-card){height:100%;padding:16px}.credential-cards :deep(.credential-facts){grid-template-columns:repeat(2,minmax(0,1fr));gap:8px 16px;margin:16px 0}.credential-cards :deep(.credential-actions){gap:8px}.credential-cards :deep(.credential-actions button){min-height:var(--control-height);padding:8px 8px;font-size:11px}

.section-heading h2 {
  font-size:18px;

}

.credential-toolbar {
  display:flex;
  gap:8px;

}

.search-field {
  position:relative;
  min-width:0;
  flex:1;

}

.search-field svg {
  position:absolute;
  top:14px;
  left:12px;
  color:var(--muted);

}

.search-field input {
  padding-left:40px;
  font-size:13px;

}

.filter-field select {
  min-height:var(--control-height);
  max-width:100%;
  padding:8px 24px 8px 16px;
  background:white;
  border:1px solid var(--line);
  border-radius:8px;
  color:var(--ink);
  font-size:12px;

}

.search-empty {
  font-size:13px;
  color:var(--muted);
  padding:16px;
  border:1px dashed var(--line);
  border-radius:16px;

}

.text-button {
  padding-inline:8px;

}

.rotation-form {
  margin-top:16px;
  display:grid;
  gap:8px;
  background:var(--page);
  border:1px solid var(--line);
  border-radius:8px;
  padding:16px;

}

.sr-only {
  position:absolute;
  width:1px;
  height:1px;
  padding:0;
  margin:-8px;
  overflow:hidden;
  clip:rect(0,0,0,0);
  white-space:nowrap;
  border:0;

}
@media(min-width:1050px){.credential-workspace{grid-template-columns:minmax(270px,310px) minmax(0,1fr)}}
@media(max-width:640px){.credential-workspace{gap:8px}.credential-add{padding:16px}.credential-cards{grid-template-columns:minmax(0,1fr)}.credential-cards :deep(.credential-facts){grid-template-columns:minmax(0,1fr)}.credential-toolbar{flex-wrap:wrap}.search-field{flex-basis:100%}.filter-field{width:100%}.filter-field select{width:100%}.credential-create-grid>.credential-actions{display:grid;grid-template-columns:minmax(0,1fr)}.credential-create-grid>.credential-actions button{width:100%}.rotation-form>.credential-actions{display:grid;grid-template-columns:repeat(2,minmax(0,1fr))}.rotation-form>.credential-actions button{width:100%}}
</style>
