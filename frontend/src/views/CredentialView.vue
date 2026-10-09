<script setup>
import { computed, inject, onMounted, onUnmounted, ref } from 'vue';
import { onBeforeRouteLeave } from 'vue-router';

const api = inject('credentialApi');
const credentials = ref([]);
const listStatus = ref('loading');
const loading = computed(() => listStatus.value === 'loading');
let listRequestId = 0;
const loadingError = ref('');
const errorMessage = ref('');
const successMessage = ref('');
const creating = ref(false);
const busyCredentialId = ref('');
const label = ref('');
const createToken = ref('');
const rotationCredentialId = ref('');
const rotationToken = ref('');

const expiryLabels = {
  expiry_unknown: '到期时间未知',
  expiry_ok: '有效期正常',
  expiring_soon: '即将过期',
  expired: '已过期',
};
const validationLabels = {
  never_confirmed: '尚未确认',
  confirmed_valid: '已验证有效',
  confirmed_invalid: '已确认无效',
};
const bindingLabels = {
  unresolved: '尚未确认',
  confirmed: '已确认',
  needs_reconfirmation: '需要重新确认',
};
const attemptLabels = {
  success: '验证成功',
  explicit_invalid: 'Token 已确认无效',
  network_error: '网络错误',
  rate_limited: '受到限流',
  contract_drift: '上游协议变化',
  validation_unknown: '结果未知',
  unresolved_identity: 'Token 已验证，账户连续性未确认',
  internal_error: '验证暂不可用',
};
const operationLabels = {
  create_candidate: '添加 Token',
  validate_current: '验证当前 Token',
  token_rotation_candidate: '验证替换 Token',
};
const safeErrors = {
  invalid_request: '输入内容无效，请检查后重试。',
  invalid_credential_label: '名称长度须为 1 到 128 个字符，且不能包含控制字符。',
  invalid_credential_token: 'Token 格式无效，请重新输入。',
  credential_token_expired: '此 Token 已过期，请替换 Token。',
  credential_token_invalid: '此 Token 已确认无效，请替换 Token。',
  credential_account_already_configured: '此上游账户已绑定到本用户的其他凭据，请重新启用或轮换已有凭据。',
  credential_account_binding_unresolved: '账户连续性尚未确认；请先验证现有凭据或删除后重新添加。',
  credential_account_reconfirmation_required: '账户连续性需要重新确认；当前凭据不能轮换。',
  credential_account_mismatch: '替换 Token 与当前账户不匹配，原凭据保持不变。',
  credential_version_conflict: '凭据已更新，请刷新后重试。',
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

function safeMessage(error) {
  return safeErrors[error?.code] || '操作未完成，请重试。';
}

function formatDate(value) {
  if (!value) return '—';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '—';
  return new Intl.DateTimeFormat('zh-CN', {
    dateStyle: 'medium',
    timeStyle: 'short',
  }).format(date);
}

function expiryText(value) {
  return expiryLabels[value] || '到期时间未知';
}

function validationText(value) {
  return validationLabels[value] || '验证状态未知';
}

function bindingText(value) {
  return bindingLabels[value] || '账户状态未知';
}

function attemptText(value) {
  return attemptLabels[value] || '验证结果未知';
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
  } catch (error) {
    if (requestId !== listRequestId) return;
    loadingError.value = safeMessage(error);
    listStatus.value = 'error';
  }
}

function clearSensitiveInputs() {
  createToken.value = '';
  rotationToken.value = '';
  rotationCredentialId.value = '';
}

function cancelCreate() {
  label.value = '';
  createToken.value = '';
  errorMessage.value = '';
}

function beginRotation(credentialId) {
  errorMessage.value = '';
  rotationCredentialId.value = credentialId;
  rotationToken.value = '';
}

function cancelRotation() {
  rotationToken.value = '';
  rotationCredentialId.value = '';
  errorMessage.value = '';
}

async function createCredential() {
  if (creating.value) return;
  creating.value = true;
  errorMessage.value = '';
  successMessage.value = '';
  const submittedLabel = label.value;
  const submittedToken = createToken.value;
  try {
    await api.create({ label: submittedLabel, token: submittedToken });
    label.value = '';
    successMessage.value = '凭据已添加。';
    await loadCredentials();
  } catch (error) {
    errorMessage.value = safeMessage(error);
  } finally {
    createToken.value = '';
    creating.value = false;
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
    errorMessage.value = safeMessage(error);
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
    `确认删除“${credential.label}”吗？已保存的 Token 会被清除，且此操作无法撤销。`,
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
    errorMessage.value = safeMessage(error);
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
    <header class="credential-heading">
      <div>
        <p class="eyebrow">账号安全</p>
        <h1 id="credential-title">预约凭据</h1>
        <p class="muted">
          Token 只用于只读验证和安全保存。账户连续性、有效期与验证结果分别显示。
        </p>
      </div>
    </header>

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

    <section class="credential-add panel" aria-labelledby="credential-add-title">
      <h2 id="credential-add-title">添加预约凭据</h2>
      <p class="muted">
        Token 会在服务器端加密保存。验证完成后会清空输入框；Token 不会放入浏览器地址或本地存储。
      </p>
      <form class="form-stack" data-testid="credential-create" @submit.prevent="createCredential">
        <label class="field">
          凭据名称
          <input
            v-model="label"
            data-testid="credential-label"
            type="text"
            maxlength="128"
            autocomplete="off"
            required
          />
        </label>
        <label class="field">
          上游 Token
          <input
            v-model="createToken"
            data-testid="credential-token"
            type="password"
            autocomplete="off"
            spellcheck="false"
            required
          />
        </label>
        <div class="credential-actions">
          <button class="primary-button" type="submit" :disabled="creating">
            {{ creating ? '验证并保存中…' : '验证并保存' }}
          </button>
          <button
            class="secondary-button"
            type="button"
            data-testid="credential-create-cancel"
            @click="cancelCreate"
          >清空</button>
        </div>
      </form>
    </section>

    <section class="credential-list" aria-labelledby="credential-list-title" :aria-busy="loading">
      <div class="section-heading">
        <h2 id="credential-list-title">已保存凭据</h2>
        <button class="text-button" type="button" :disabled="loading" @click="loadCredentials()">
          刷新
        </button>
      </div>
      <p v-if="loading" class="muted" role="status">正在读取凭据状态…</p>
      <p v-else-if="listStatus === 'ready' && credentials.length === 0" class="empty-state">
        暂无预约凭据。添加后可查看 Token 状态和账户连续性。
      </p>

      <template v-if="listStatus === 'ready'">
      <article
        v-for="credential in credentials"
        :key="credential.credential_id"
        class="credential-card"
        :data-testid="`credential-card-${credential.credential_id}`"
      >
        <header class="credential-card-heading">
          <div>
            <h3>{{ credential.label }}</h3>
            <p class="muted">版本 {{ credential.credential_version }}</p>
          </div>
          <span class="state-pill" :class="credential.enabled ? 'state-enabled' : 'state-disabled'">
            {{ credential.enabled ? '已启用' : '已停用' }}
          </span>
        </header>

        <dl class="credential-facts">
          <div>
            <dt>账户连续性</dt>
            <dd>{{ bindingText(credential.account_binding_state) }}</dd>
          </div>
          <div>
            <dt>Token 验证</dt>
            <dd>{{ validationText(credential.last_confirmed_validation_state) }}</dd>
          </div>
          <div>
            <dt>有效期</dt>
            <dd>{{ expiryText(credential.expiry_state) }}</dd>
          </div>
          <div>
            <dt>Token 到期时间</dt>
            <dd>{{ formatDate(credential.token_expires_at_utc) }}</dd>
          </div>
          <div>
            <dt>最近成功验证</dt>
            <dd>{{ formatDate(credential.last_successful_validation_at_utc) }}</dd>
          </div>
          <div>
            <dt>最近发起的验证</dt>
            <dd v-if="credential.latest_requested_validation_attempt">
              {{ operationLabels[credential.latest_requested_validation_attempt.operation_kind] || '验证请求' }}：
              {{ attemptText(credential.latest_requested_validation_attempt.attempt_result) }}
              <span class="muted">
                （开始 {{ formatDate(credential.latest_requested_validation_attempt.started_at_utc) }}；
                完成 {{ formatDate(credential.latest_requested_validation_attempt.completed_at_utc) }}）
              </span>
            </dd>
            <dd v-else>尚无验证请求</dd>
          </div>
        </dl>

        <p v-if="credential.expiry_state === 'expiring_soon'" class="risk-note">
          Token 即将到期，请提前准备替换 Token。此提醒本身不会阻止当前凭据使用。
        </p>
        <p v-if="credential.expiry_state === 'expired' || credential.last_confirmed_validation_state === 'confirmed_invalid'" class="risk-note danger-note">
          当前 Token 已过期或已确认无效，需验证新的 Token 后才能继续使用。
        </p>
        <p v-if="credential.requires_revalidation" class="risk-note">
          凭据重新启用后需要再次验证当前 Token。
        </p>
        <p v-if="credential.account_binding_state === 'unresolved'" class="risk-note">
          账户连续性尚未确认。此凭据不能轮换 Token，也不能用于依赖上游账户身份的后续预约任务；可重新验证当前 Token 以尝试确认。
        </p>
        <p v-if="credential.account_binding_state === 'needs_reconfirmation'" class="risk-note danger-note">
          账户连续性需要重新确认。轮换和后续账户级使用已暂停；验证当前 Token 并匹配原账户后才能恢复。
        </p>

        <div class="credential-actions">
          <button
            v-if="credential.enabled"
            class="secondary-button"
            type="button"
            :data-testid="`validate-${credential.credential_id}`"
            :disabled="busyCredentialId === credential.credential_id"
            @click="validateCredential(credential)"
          >
            {{ busyCredentialId === credential.credential_id ? '处理中…' : '验证当前 Token' }}
          </button>
          <button
            v-if="credential.enabled && credential.account_binding_state === 'confirmed'"
            class="secondary-button"
            type="button"
            :data-testid="`rotate-${credential.credential_id}`"
            :disabled="busyCredentialId === credential.credential_id"
            @click="beginRotation(credential.credential_id)"
          >
            轮换 Token
          </button>
          <button
            class="secondary-button"
            type="button"
            :data-testid="`credential-${credential.enabled ? 'disable' : 'enable'}-${credential.credential_id}`"
            :disabled="busyCredentialId === credential.credential_id"
            @click="toggleEnabled(credential)"
          >
            {{ credential.enabled ? '停用' : '重新启用' }}
          </button>
          <button
            class="danger-button"
            type="button"
            :data-testid="`credential-delete-${credential.credential_id}`"
            :disabled="busyCredentialId === credential.credential_id"
            @click="deleteCredential(credential)"
          >
            删除
          </button>
        </div>

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
      </article>
      </template>
    </section>
  </section>
</template>

<style scoped>
.credential-page { display: grid; gap: 1.25rem; }
.credential-heading h1 { margin: 0 0 .4rem; font-size: clamp(1.6rem, 4vw, 2rem); }
.eyebrow { margin: 0 0 .25rem; color: #58716c; font-size: .78rem; font-weight: 750; letter-spacing: .08em; text-transform: uppercase; }
.credential-add { width: 100%; margin: 0; }
.credential-add h2, .section-heading h2 { margin: 0; font-size: 1.1rem; }
.section-heading { display: flex; align-items: center; justify-content: space-between; gap: 1rem; }
.credential-list { display: grid; gap: .9rem; }
.credential-card { display: grid; gap: 1rem; padding: 1.2rem; border: 1px solid #e1e7ec; border-radius: .9rem; background: white; }
.credential-card-heading { display: flex; align-items: flex-start; justify-content: space-between; gap: 1rem; }
.credential-card-heading h3 { margin: 0 0 .2rem; font-size: 1.05rem; }
.credential-card-heading p { margin: 0; font-size: .84rem; }
.state-pill { padding: .25rem .6rem; border-radius: 999px; font-size: .78rem; font-weight: 700; }
.state-enabled { color: #155a45; background: #e4f3eb; }
.state-disabled { color: #52606d; background: #edf0f2; }
.credential-facts { display: grid; grid-template-columns: repeat(auto-fit, minmax(12rem, 1fr)); gap: .8rem 1.25rem; margin: 0; }
.credential-facts div { min-width: 0; }
.credential-facts dt { color: #65717e; font-size: .78rem; }
.credential-facts dd { margin: .2rem 0 0; color: #253545; font-size: .9rem; line-height: 1.5; overflow-wrap: anywhere; }
.risk-note { margin: 0; padding: .7rem .85rem; border-left: 3px solid #b98222; border-radius: .35rem; color: #5c461b; background: #fff8e9; line-height: 1.5; }
.danger-note { border-left-color: #a94343; color: #713333; background: #fff0f0; }
.credential-actions { display: flex; flex-wrap: wrap; gap: .6rem; }
.credential-actions .primary-button, .credential-actions .secondary-button, .danger-button { min-height: 2.4rem; padding: .5rem .8rem; }
.danger-button { border: 0; border-radius: .6rem; color: #8f2929; background: #fbe8e8; font: inherit; font-weight: 700; cursor: pointer; }
.danger-button:disabled { opacity: .6; cursor: wait; }
.rotation-form { display: grid; gap: .8rem; padding: 1rem; border-radius: .7rem; background: #f4f7f8; }
.credential-message { margin: 0; padding: .75rem .9rem; border-radius: .6rem; background: white; }
.error-message { color: #8f2929; }
.success-message { color: #176348; }
.empty-state { margin: 0; padding: 1.2rem; border: 1px dashed #cbd5df; border-radius: .8rem; color: #65717e; background: white; }
.text-button { padding: .2rem .4rem; border: 0; color: #146c5b; background: transparent; font: inherit; font-weight: 700; cursor: pointer; }
.text-button:disabled { opacity: .6; cursor: wait; }
</style>
