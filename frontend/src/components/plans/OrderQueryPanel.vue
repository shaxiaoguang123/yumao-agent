<script setup>
import { computed, onBeforeUnmount, shallowRef, watch } from 'vue';
import AppIcon from '../AppIcon.vue';
import OrderDetailPanel from './OrderDetailPanel.vue';
import { orderErrorMessage } from '../../api/orders.js';

const props = defineProps({ api: Object, session: Object, credentialId: String, refreshKey: Number });
const result = shallowRef(null), loading = shallowRef(false), error = shallowRef(''), options = shallowRef([]);
const status = shallowRef(''), page = shallowRef(1), selected = shallowRef('');
let sequence = 0, alive = true;
const authenticated = () => props.session?.status === 'authenticated' && Boolean(props.session?.user?.user_id);
const refreshedAt = computed(() => Number.isSafeInteger(result.value?.queried_at_utc_ms)
  ? new Intl.DateTimeFormat('zh-CN', { timeZone: 'Asia/Shanghai', hour: '2-digit', minute: '2-digit', second: '2-digit' }).format(result.value.queried_at_utc_ms)
  : '');
async function load(targetPage = page.value) {
  if (!authenticated() || !props.credentialId || !props.api) return;
  const current = ++sequence;
  loading.value = true; error.value = ''; selected.value = '';
  try {
    const value = await props.api.query({ credentialId: props.credentialId, page: targetPage, status: status.value });
    if (!alive || current !== sequence) return;
    if (!Array.isArray(value?.orders) || !Array.isArray(value.status_options)
      || !Number.isSafeInteger(value.page) || typeof value.has_next !== 'boolean') throw new Error('invalid_response');
    result.value = value; options.value = value.status_options; page.value = value.page;
  } catch (failure) {
    if (alive && current === sequence) {
      error.value = orderErrorMessage(failure);
      if (failure?.retryAfterSeconds) error.value += ` 请等待 ${failure.retryAfterSeconds} 秒。`;
    }
  } finally {
    if (alive && current === sequence) loading.value = false;
  }
}
function changeFilter() { result.value = null; page.value = 1; void load(1); }
watch(() => [props.credentialId, props.refreshKey, props.session?.status, props.session?.user?.user_id, props.session?.csrfToken, props.session?.invalidationEpoch], () => {
  sequence++; result.value = null; options.value = []; error.value = ''; selected.value = ''; status.value = ''; page.value = 1; loading.value = false;
  if (authenticated()) void load(1);
}, { immediate: true, flush: 'sync' });
onBeforeUnmount(() => { alive = false; sequence++; });
</script>

<template>
  <section class="order-query-panel" aria-labelledby="order-query-title" data-testid="order-query-panel">
    <header class="order-query-heading">
      <div><p class="eyebrow">官方订单</p><h2 id="order-query-title">查询订单</h2><p class="muted">查看当前 Token 的预约与订单状态。</p></div>
      <slot name="credentials" />
    </header>
    <div class="order-query-toolbar">
      <label class="field">订单状态<select v-model="status" :disabled="loading || !credentialId" @change="changeFilter"><option value="">全部状态</option><option v-for="option in options" :key="option.code" :value="option.code">{{ option.label }}</option></select></label>
      <span v-if="refreshedAt" class="order-refreshed-at">最近读取 {{ refreshedAt }}</span>
      <button class="secondary-button" type="button" :disabled="loading || !credentialId" @click="load(page)"><AppIcon name="refresh" />{{ loading ? '读取中…' : '刷新订单' }}</button>
    </div>
    <p v-if="!credentialId" class="order-empty">请选择已验证的 Token 后查询订单。</p>
    <p v-if="error" class="form-error" role="alert">{{ error }} <RouterLink to="/credentials">管理凭据</RouterLink></p>
    <p v-if="loading" class="muted" role="status">正在读取官方订单…</p>
    <div v-if="result?.orders.length" class="order-list" :aria-busy="loading">
      <article v-for="order in result.orders" :key="order.reference" class="order-card" data-testid="order-card">
        <div class="order-card-summary">
          <div class="order-card-main"><h3>{{ order.venue_name || '预约场地' }}</h3><p>{{ order.booking_time || order.appointment_date || '时间暂未返回' }}</p></div>
          <span class="order-status" :class="{ 'is-pending': order.status === '5', 'is-confirmed': order.reservation_confirmed }">{{ order.status_label }}</span>
          <strong class="order-amount">{{ order.amount_display === null ? '金额待确认' : `¥${order.amount_display}` }}</strong>
          <button class="text-button" type="button" :aria-expanded="selected === order.reference" :aria-label="`查看${order.venue_name || '预约'}${order.booking_time || ''}订单详情`" @click="selected = selected === order.reference ? '' : order.reference">{{ selected === order.reference ? '收起' : '查看详情' }}<AppIcon :name="selected === order.reference ? 'up' : 'down'" /></button>
        </div>
        <OrderDetailPanel v-if="selected === order.reference" :api="api" :credential-id="credentialId" :reference="order.reference" @close="selected = ''" @refresh="load(page)" />
      </article>
    </div>
    <p v-else-if="result && !loading && !error" class="order-empty">当前 Token 在此状态下暂无订单。</p>
    <footer v-if="result" class="order-pagination" aria-label="订单分页">
      <span>共 {{ result.total }} 条 · 第 {{ result.page }} / {{ Math.max(1, result.total_pages) }} 页</span>
      <div><button class="secondary-button" type="button" :disabled="loading || page <= 1" @click="load(page - 1)">上一页</button><button class="secondary-button" type="button" :disabled="loading || !result.has_next" @click="load(page + 1)">下一页</button></div>
    </footer>
  </section>
</template>

<style scoped>
.order-query-panel{min-width:0}.order-query-heading{display:flex;align-items:center;justify-content:space-between;gap:20px;padding:24px;background:var(--surface);border:1px solid var(--line);border-radius:16px}.order-query-heading>div{min-width:0}.order-query-heading h2{font-size:24px;font-weight:600;letter-spacing:-.02em;margin:4px 0 8px}.order-query-heading p{margin:0;font-size:14px;line-height:1.6}.order-query-heading .eyebrow{color:var(--brand-dark);font-size:12px}.order-query-toolbar{display:flex;align-items:flex-end;flex-wrap:wrap;gap:16px;padding:20px 0}.order-query-toolbar .field{min-width:160px;font-size:13px;gap:6px}.order-query-toolbar select{min-height:44px;border:1px solid var(--line);border-radius:12px;background:var(--surface);font:inherit;color:var(--ink);padding:8px 12px}.order-query-toolbar button{display:flex;align-items:center;gap:8px;min-height:44px}.order-refreshed-at{margin-left:auto;align-self:center;font-size:12px;color:var(--muted)}.order-list{display:grid;gap:12px}.order-card{min-width:0;background:var(--surface);border:1px solid var(--line);border-radius:16px;padding:20px 24px}.order-card-summary{display:grid;grid-template-columns:minmax(0,1fr) auto auto auto;align-items:center;gap:20px}.order-card-main{min-width:0}.order-card h3{font-size:16px;margin:0 0 6px;font-weight:600}.order-card p{font-size:14px;margin:0;color:var(--muted);line-height:1.6;overflow-wrap:anywhere}.order-status{font-size:12px;background:var(--page);color:var(--muted);padding:6px 10px;border-radius:999px;line-height:1.5}.order-status.is-confirmed{color:var(--brand-dark);background:var(--brand-soft)}.order-status.is-pending{color:var(--ink);background:var(--warning-soft)}.order-amount{font-size:17px;font-weight:600;font-variant-numeric:tabular-nums}.order-card-summary>button{display:flex;align-items:center;gap:6px;min-height:44px;white-space:nowrap}.order-card .app-icon{width:16px;height:16px}.order-empty{padding:36px 20px;text-align:center;color:var(--muted);background:var(--surface);border:1px dashed var(--line);border-radius:16px;line-height:1.8}.order-pagination{display:flex;align-items:center;justify-content:space-between;gap:16px;margin-top:20px;font-size:13px;color:var(--muted)}.order-pagination>div{display:flex;gap:10px}.order-pagination button{min-height:44px}.form-error{line-height:1.8}.form-error a{white-space:nowrap}@media(max-width:700px){.order-query-heading{padding:20px;align-items:flex-start;flex-wrap:wrap}.order-query-heading h2{font-size:22px}.order-card{padding:16px}.order-card-summary{grid-template-columns:minmax(0,1fr) auto;gap:12px}.order-card-main{grid-row:1/3}.order-status{justify-self:end;max-width:140px;text-align:center}.order-amount{justify-self:end}.order-card-summary>button{grid-column:1/-1;justify-content:flex-end;border-top:1px solid var(--line);padding-top:10px}.order-pagination{flex-wrap:wrap}.order-pagination>div{margin-left:auto}.order-refreshed-at{order:3;flex-basis:100%;margin:0}.order-query-toolbar{gap:12px}.order-query-toolbar .field{flex:1;min-width:140px}}
</style>
