<script setup>
import { computed, inject, onBeforeUnmount, onMounted, ref } from 'vue';
import { RouterLink } from 'vue-router';

import AppIcon from '../components/AppIcon.vue';
import PageHeader from '../components/PageHeader.vue';
import ActivityOverview from '../components/metrics/ActivityOverview.vue';
import { needsAttention } from '../utils/credentialSummary.js';
const sessionStore = inject('sessionStore');
const api = inject('credentialApi');
const credentials = ref([]);
const credentialStatus = ref('loading');

let requestId = 0;
const enabledCount = computed(() => credentials.value.filter(item => item.enabled).length);
const attentionCount = computed(() => credentials.value.filter(needsAttention).length);
const metric = count => credentialStatus.value === 'ready' ? count : '—';
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
  const currentRequest = ++requestId;
  credentialStatus.value = 'loading';
  try {
    const result = await api.list();
    if (!Array.isArray(result?.credentials)) throw new Error('invalid_response');
    if (currentRequest !== requestId) return;
    credentials.value = result.credentials;
    credentialStatus.value = 'ready';
  } catch {
    if (currentRequest !== requestId) return;
    credentialStatus.value = 'unavailable';
  }
}

onMounted(loadCredentialSummary);
onBeforeUnmount(() => { requestId += 1; });
</script>
<template>
 <div class="dashboard-page">
  <template v-if="sessionStore.status === 'unavailable'"><section class="panel"><h1>暂时无法确认登录状态</h1><p class="muted" role="alert">{{ sessionStore.errorMessage || '请检查连接后重试。' }}</p><button class="secondary-button" type="button" @click="sessionStore.refresh()">重试</button></section></template>
  <PageHeader v-else :title="`你好，${sessionStore.user?.username || '用户'}`"><RouterLink class="primary-button" :to="{name:'plans'}">开始预约<AppIcon name="arrow" /></RouterLink></PageHeader>
  <section class="panel credential-home-summary" aria-labelledby="credential-summary-title">
   <div class="summary-heading"><h2 id="credential-summary-title">预约凭据状态</h2><RouterLink class="action-link" :to="{name:'credentials'}">管理凭据<AppIcon name="arrow" /></RouterLink></div>
  <section class="overview-metrics" aria-label="凭据概览"><div><span>已保存凭据</span><strong data-testid="total-credentials">{{ metric(credentials.length) }}</strong><small>仅当前账户</small></div><div><span>已启用</span><strong data-testid="enabled-credentials">{{ metric(enabledCount) }}</strong><small>启用不代表可预约</small></div><div><span>需要关注</span><strong data-testid="attention-credentials">{{ metric(attentionCount) }}</strong><small>到期、验证与身份提醒</small></div></section>
    <p v-if="credentialStatus==='loading'" class="muted" role="status">正在读取凭据状态…</p>
    <div v-else-if="credentialStatus==='unavailable'" class="overview-error"><p class="muted" role="status">暂时无法读取凭据状态，请稍后重试。</p><button data-testid="retry-summary" class="secondary-button" type="button" @click="loadCredentialSummary"><AppIcon name="refresh" />重试</button></div>
    <p v-else-if="credentials.length===0" class="empty-state">尚未添加预约凭据。</p>
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
  <ActivityOverview />
 </div>
</template>
<style scoped>
.dashboard-page { display:grid; gap:16px; }
.dashboard-page .page-header { margin-bottom:0; }
.summary-heading { display:flex; align-items:center; justify-content:space-between; gap:12px; }
.summary-heading h2 { font-size:16px; }
.summary-heading .action-link { flex:none; padding-inline:8px; }
.overview-metrics { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); margin:12px 0; padding:0; }
.overview-metrics > div { display:grid; gap:4px; min-width:0; padding:0 20px; border-right:1px solid var(--line); }
.overview-metrics > div:first-child { padding-left:0; }
.overview-metrics > div:last-child { border:0; }
.overview-metrics span,.overview-metrics small { color:var(--muted); font-size:12px; }
.overview-metrics strong { font-size:30px; line-height:1.2; font-weight:600; font-variant-numeric:tabular-nums; }
.risk-list { display:flex; flex-wrap:wrap; gap:6px 20px; margin:16px 0 0; padding:12px 0 0; border-top:1px solid var(--line); list-style:none; font-size:13px; }
.risk-high { color:var(--danger); }
.risk-reminder { color:var(--warning); }
.overview-error { display:flex; align-items:center; justify-content:space-between; gap:8px; }
.overview-error p { margin:0; }
@media(max-width:600px) {
 .dashboard-page { gap:12px; }
 .overview-metrics > div { padding-inline:12px; }
 .overview-metrics small { font-size:11px; }
 .summary-heading h2 { font-size:15px; }
}
</style>
