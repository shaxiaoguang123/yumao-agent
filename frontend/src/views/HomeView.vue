<script setup>
import { computed, inject, onMounted, ref } from 'vue';
import { RouterLink } from 'vue-router';

const sessionStore = inject('sessionStore');
const api = inject('credentialApi');
const credentials = ref([]);
const credentialStatus = ref('loading');

const expiredCount = computed(() => credentials.value.filter((item) => (
  item.expiry_state === 'expired' || item.last_confirmed_validation_state === 'confirmed_invalid'
)).length);
const expiringCount = computed(() => credentials.value.filter((item) => item.expiry_state === 'expiring_soon').length);
const unresolvedCount = computed(() => credentials.value.filter((item) => (
  item.account_binding_state === 'unresolved'
)).length);
const reconfirmationCount = computed(() => credentials.value.filter((item) => (
  item.account_binding_state === 'needs_reconfirmation'
)).length);
const revalidationCount = computed(() => credentials.value.filter((item) => item.requires_revalidation).length);

async function loadCredentialSummary() {
  credentialStatus.value = 'loading';
  try {
    const result = await api.list();
    if (!Array.isArray(result?.credentials)) throw new Error('invalid_response');
    credentials.value = result.credentials;
    credentialStatus.value = 'ready';
  } catch {
    credentialStatus.value = 'unavailable';
  }
}

onMounted(loadCredentialSummary);
</script>

<template>
  <section class="panel home-panel">
    <template v-if="sessionStore.status === 'unavailable'">
      <h1>暂时无法确认登录状态</h1>
      <p class="muted" role="alert">{{ sessionStore.errorMessage || '请检查连接后重试。' }}</p>
      <button class="secondary-button" type="button" @click="sessionStore.refresh()">重试</button>
    </template>
    <template v-else>
      <h1>你好，{{ sessionStore.user?.username || '用户' }}</h1>
      <p class="muted">身份基础已就绪。预约计划和自动执行功能将在后续阶段接入。</p>
      <RouterLink :to="{ name: 'account' }">管理账户与密码</RouterLink>
    </template>
  </section>

  <section class="panel home-panel credential-home-summary" aria-labelledby="credential-summary-title">
    <div class="summary-heading">
      <div>
        <h2 id="credential-summary-title">预约凭据状态</h2>
        <p class="muted">只显示当前账户的凭据风险摘要。</p>
      </div>
      <RouterLink :to="{ name: 'credentials' }">管理凭据</RouterLink>
    </div>
    <p v-if="credentialStatus === 'loading'" class="muted" role="status">正在读取凭据状态…</p>
    <p v-else-if="credentialStatus === 'unavailable'" class="muted" role="status">
      暂时无法读取凭据状态，请稍后重试。
    </p>
    <p v-else-if="credentials.length === 0" class="muted">
      尚未添加预约凭据。
    </p>
    <ul v-else class="risk-list">
      <li v-if="expiredCount" class="risk-high">
        {{ expiredCount }} 个凭据的 Token 已过期或已确认无效，请优先处理。
      </li>
      <li v-if="reconfirmationCount" class="risk-high">
        {{ reconfirmationCount }} 个凭据需要重新确认账户连续性，账户级使用已暂停。
      </li>
      <li v-if="unresolvedCount">
        {{ unresolvedCount }} 个凭据的账户连续性尚未确认，不能用于依赖账户身份的后续预约任务。
      </li>
      <li v-if="revalidationCount">
        {{ revalidationCount }} 个凭据需要重新验证当前 Token。
      </li>
      <li v-if="expiringCount" class="risk-reminder">
        {{ expiringCount }} 个凭据的 Token 即将到期，请提前准备轮换。此提醒本身不会阻止使用。
      </li>
      <li v-if="!expiredCount && !reconfirmationCount && !unresolvedCount && !revalidationCount && !expiringCount">
        当前没有需要处理的凭据风险。
      </li>
    </ul>
  </section>
</template>

<style scoped>
.home-panel { width: 100%; margin: 0 0 1.25rem; }
.summary-heading { display: flex; align-items: flex-start; justify-content: space-between; gap: 1rem; }
.summary-heading h2 { margin: 0; font-size: 1.15rem; }
.summary-heading p { margin: .3rem 0 0; }
.risk-list { display: grid; gap: .6rem; margin: 1rem 0 0; padding-left: 1.25rem; line-height: 1.5; }
.risk-high { color: #8f2929; }
.risk-reminder { color: #755518; }
</style>
