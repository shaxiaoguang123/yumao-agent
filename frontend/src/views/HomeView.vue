<script setup>
import { computed, inject, onBeforeUnmount, onMounted, ref } from 'vue';
import { RouterLink } from 'vue-router';

import AppIcon from '../components/AppIcon.vue';
import PageHeader from '../components/PageHeader.vue';
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
  <PageHeader v-else eyebrow="你的运动工作空间" :title="`你好，${sessionStore.user?.username || '用户'}`" description="先把账户与凭据准备好，再从容规划你的下一次上场。"><RouterLink class="secondary-button" :to="{name:'account'}"><AppIcon name="user" />管理账户与密码</RouterLink></PageHeader>
  <section class="dashboard-hero"><div><span class="hero-label"><span class="availability-dot" />账户与凭据管理已开放</span><h2>专注上场，准备有序。</h2><p>把凭据、安全与状态整理在一起，<br class="desktop-break" />让每一次准备都更清晰。</p></div><div class="hero-court" aria-hidden="true"><AppIcon name="court" /></div></section>
  <section class="overview-metrics" aria-label="凭据概览"><div><span>已保存凭据</span><strong data-testid="total-credentials">{{ metric(credentials.length) }}</strong><small>仅当前账户</small></div><div><span>已启用</span><strong data-testid="enabled-credentials">{{ metric(enabledCount) }}</strong><small>启用不代表可预约</small></div><div><span>需要关注</span><strong data-testid="attention-credentials">{{ metric(attentionCount) }}</strong><small>到期、验证与身份提醒</small></div></section>
  <div class="dashboard-grid">
   <section class="panel credential-home-summary" aria-labelledby="credential-summary-title"><div class="summary-heading"><div><p class="eyebrow">CREDENTIAL HEALTH</p><h2 id="credential-summary-title">预约凭据状态</h2><p class="muted">只显示当前账户的凭据风险摘要。</p></div><RouterLink class="action-link" :to="{name:'credentials'}">管理凭据<AppIcon name="arrow" /></RouterLink></div>
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
   <aside class="scope-panel"><span class="section-icon"><AppIcon name="court" /></span><h2>一步一步，准备到位</h2><p>当前可管理账户、预约凭据与邀请码。凭据验证不等于已创建预约。</p><div class="scope-status"><span>预约计划 · 自动执行 · 支付</span><strong>尚未开放</strong></div><p class="scope-footnote">功能状态以实际实现为准。</p></aside>
  </div>
 </div>
</template>
<style scoped>
.dashboard-hero {
  position:relative;
  display:flex;
  justify-content:space-between;
  align-items:center;
  min-height:205px;
  padding:32px 36px;
  border-radius:18px;
  color:white;
  background:var(--brand-dark);
  overflow:clip;

}

.hero-label {
  display:inline-flex;
  align-items:center;
  padding:6px 10px;
  border:1px solid #476152;
  border-radius:5px;
  font-size:11px;
  color:#d7e9d4;

}

.hero-label .availability-dot {
  background:var(--accent);

}

.dashboard-hero h2 {
  margin-top:19px;
  font-size:30px;
  letter-spacing:-.04em;

}

.dashboard-hero p {
  margin:12px 0 0;
  color:#c2d1c6;
  font-size:13px;

}

.hero-court {
  margin-right:35px;
  transform:rotate(-20deg);
  color:var(--accent);
  opacity:.65;

}

.hero-court svg {
  width:150px;
  height:170px;
  stroke-width:.7;

}

.overview-metrics {
  display:grid;
  grid-template-columns:repeat(3,minmax(0,1fr));
  margin:24px 0;
  padding:26px 8px;
  border-bottom:1px solid var(--line);

}

.overview-metrics > div {
  display:grid;
  gap:9px;
  padding:0 24px;
  border-right:1px solid var(--line);

}

.overview-metrics > div:last-child {
  border:0;

}

.overview-metrics span {
  font-size:12px;
  color:var(--muted);

}

.overview-metrics strong {
  font-size:36px;
  line-height:1;
  letter-spacing:-.04em;
  font-weight:650;

}

.overview-metrics small {
  font-size:11px;
  color:var(--muted);
  line-height:1.6;

}

.dashboard-grid {
  display:grid;
  grid-template-columns:minmax(0,1.65fr) minmax(0,1fr);
  gap:24px;

}

.summary-heading {
  display:flex;
  flex-wrap:wrap;
  align-items:center;
  justify-content:space-between;
  gap:10px;

}

.summary-heading > div {
  flex:1 1 200px;
  min-width:0;

}

.summary-heading p.muted {
  font-size:12px;
  margin:8px 0 0;

}

.summary-heading > a {
  flex-shrink:0;
  padding-inline:8px;

}

.risk-list {
  display:grid;
  gap:0;
  padding:0;
  margin:20px 0 0;
  list-style:none;

}

.risk-list li {
  position:relative;
  border-top:1px solid var(--line);
  padding:14px 0 14px 18px;
  font-size:13px;
  line-height:1.8;

}

.risk-list li:before {
  content:"";
  position:absolute;
  top:22px;
  left:0;
  width:5px;
  height:5px;
  border-radius:50%;
  background:currentColor;

}

.risk-high {
  color:var(--danger);

}

.risk-reminder {
  color:var(--warning);

}

.scope-panel {
  padding:26px;
  border-radius:16px;
  background:#eaf0e8;

}

.scope-panel h2 {
  margin-top:19px;
  font-size:17px;

}

.scope-panel p {
  color:#617663;
  font-size:13px;

}

.scope-status {
  display:grid;
  gap:10px;
  border-top:1px solid #d0dbce;
  padding-top:18px;
  margin-top:24px;
  font-size:11px;

}

.scope-status strong {
  color:#617663;
  font-weight:600;

}

.scope-footnote {
  margin:17px 0 0;
  font-size:11px!important;

}

.overview-error {
  padding-top:10px;

}
@media(max-width:640px) { .hero-court { display:none; } }

@media(max-width:700px) {
  .dashboard-grid {
  grid-template-columns:1fr;
  gap:20px;

}

.dashboard-hero {
  padding:25px;
  min-height:190px;

}

.dashboard-hero h2 {
  font-size:25px;

}

.hero-court {
  margin:0 -16px 0 10px;
  opacity:.4;

}

.hero-court svg {
  width:76px;
  height:100px;

}

.overview-metrics {
  padding:22px 0;
  margin:8px 0 22px;

}

.overview-metrics > div {
  padding:0 12px;

}

.overview-metrics > div:first-child {
  padding-left:4px;

}

.overview-metrics strong {
  font-size:29px;

}

.overview-metrics small {
  font-size:10px;

}

.overview-metrics span {
  font-size:11px;

}

.scope-panel {
  padding:22px;

}
}
@media(max-width:360px) {
  .hero-court {
  display:none;

}

.dashboard-hero {
  padding:23px;

}

.dashboard-hero h2 {
  font-size:23px;

}

.overview-metrics > div {
  padding:0 9px;

}
}
</style>
