<script setup>
import { computed, inject, onMounted, onUnmounted, ref, watch } from 'vue';
import { onBeforeRouteLeave } from 'vue-router';

import PageHeader from '../components/PageHeader.vue';
import AppIcon from '../components/AppIcon.vue';
import CredentialCard from '../components/CredentialCard.vue';
import { needsAttention } from '../utils/credentialSummary.js';
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
const search = ref('');
const filter = ref('all');
const visibleCredentials = computed(() => credentials.value.filter(item => (
 item.label.toLocaleLowerCase().includes(search.value.trim().toLocaleLowerCase())
 && (filter.value === 'all' || (filter.value === 'enabled' && item.enabled) || (filter.value === 'disabled' && !item.enabled) || (filter.value === 'attention' && needsAttention(item)))
)));
// A hidden card must not retain a rotation candidate that can reappear later.
watch([search, filter], () => {
  if (rotationCredentialId.value && !visibleCredentials.value.some(item => item.credential_id === rotationCredentialId.value)) {
    rotationToken.value = '';
    rotationCredentialId.value = '';
  }
}, { flush: 'sync' });
const label = ref('');
const createToken = ref('');
const rotationCredentialId = ref('');
const rotationToken = ref('');

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
    <PageHeader title-id="credential-title" eyebrow="账户安全 · 凭据管理" title="预约凭据" description="清晰管理 Token 有效期、验证结果与账户连续性。验证和保存不代表已经预约。" />

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
      <span class="section-icon"><AppIcon name="plus" /></span>
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
      <div v-if="listStatus === 'ready' && credentials.length" class="credential-toolbar">
       <label class="search-field"><AppIcon name="search" /><span class="sr-only">搜索凭据名称</span><input v-model="search" data-testid="credential-search" type="search" placeholder="搜索凭据名称" autocomplete="off" /></label>
       <label class="filter-field"><span class="sr-only">凭据状态</span><select v-model="filter" data-testid="credential-filter" aria-label="凭据状态"><option value="all">全部状态</option><option value="attention">需要关注</option><option value="enabled">已启用</option><option value="disabled">已停用</option></select></label>
      </div>
      <p v-if="listStatus === 'ready' && credentials.length && !visibleCredentials.length" class="search-empty">没有匹配的凭据。请调整名称或状态筛选。</p>
      <p v-if="loading" class="muted" role="status">正在读取凭据状态…</p>
      <p v-else-if="listStatus === 'ready' && credentials.length === 0" class="empty-state">
        暂无预约凭据。添加后可查看 Token 状态和账户连续性。
      </p>

      <template v-if="listStatus === 'ready'">
      <CredentialCard v-for="credential in visibleCredentials" :key="credential.credential_id" :credential="credential" :busy="Boolean(busyCredentialId)" @validate="validateCredential(credential)" @rotate="beginRotation(credential.credential_id)" @toggle="toggleEnabled(credential)" @remove="deleteCredential(credential)">
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
      </CredentialCard>
      </template>
    </section>
    </div>
  </section>
</template>

<style scoped>
.credential-message {
  margin:0 0 18px;

}

.credential-workspace {
  display:grid;
  grid-template-columns:minmax(0,1fr);
  gap:26px;
  align-items:start;

}

.credential-add h2 {
  margin-top:17px;
  font-size:18px;

}

.credential-add .muted {
  font-size:12px;
  margin:10px 0 0;

}

.credential-add .form-stack {
  gap:17px;

}

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

.section-heading h2 {
  font-size:18px;

}

.credential-toolbar {
  display:flex;
  gap:10px;

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
  min-height:48px;
  max-width:100%;
  padding:10px 28px 10px 13px;
  background:white;
  border:1px solid var(--line);
  border-radius:9px;
  color:var(--ink);
  font-size:12px;

}

.search-empty {
  font-size:13px;
  color:var(--muted);
  padding:20px;
  border:1px dashed var(--line);
  border-radius:12px;

}

.text-button {
  padding-inline:10px;

}

.rotation-form {
  margin-top:18px;
  display:grid;
  gap:12px;
  background:var(--page);
  border:1px solid var(--line);
  border-radius:10px;
  padding:18px;

}

.sr-only {
  position:absolute;
  width:1px;
  height:1px;
  padding:0;
  margin:-1px;
  overflow:hidden;
  clip:rect(0,0,0,0);
  white-space:nowrap;
  border:0;

}
@media(min-width:1200px) {
  .credential-workspace {
  grid-template-columns:280px minmax(0,1fr);

}
}
@media(max-width:360px) {
  .credential-toolbar {
  flex-wrap:wrap;

}

.filter-field {
  width:100%;

}

.filter-field select {
  width:100%;

}
}
</style>
