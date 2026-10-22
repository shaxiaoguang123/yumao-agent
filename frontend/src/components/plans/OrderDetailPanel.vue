<script setup>
import { onBeforeUnmount, shallowRef, watch } from 'vue';
import { orderErrorMessage } from '../../api/orders.js';

const props = defineProps({ api: Object, credentialId: String, reference: String });
const emit = defineEmits(['close', 'refresh']);
const detail = shallowRef(null), loading = shallowRef(false), error = shallowRef('');
const needsListRefresh = shallowRef(false);
let sequence = 0, alive = true;
async function load() {
  const current = ++sequence;
  detail.value = null; error.value = ''; loading.value = true;
  try {
    const result = await props.api.details({ credentialId: props.credentialId, reference: props.reference });
    if (!alive || current !== sequence) return;
    if (!result?.order || typeof result.order.status_label !== 'string') throw new Error('invalid_response');
    detail.value = result.order;
  } catch (failure) {
    if (alive && current === sequence) {
      error.value = orderErrorMessage(failure);
      if (failure?.retryAfterSeconds) error.value += ` 请等待 ${failure.retryAfterSeconds} 秒。`;
      needsListRefresh.value = ['order_reference_expired', 'order_not_found'].includes(failure?.code);
    }
  } finally {
    if (alive && current === sequence) loading.value = false;
  }
}
watch(() => [props.credentialId, props.reference], load, { immediate: true, flush: 'sync' });
onBeforeUnmount(() => { alive = false; sequence++; });
</script>

<template>
  <section class="order-detail" aria-label="订单详情" data-testid="order-detail">
    <header><h3>订单详情</h3><button class="text-button" type="button" @click="emit('close')">收起详情</button></header>
    <p v-if="loading" class="muted" role="status">正在读取官方订单详情…</p>
    <p v-else-if="error" class="form-error" role="alert">{{ error }} <button class="text-button" type="button" @click="needsListRefresh ? emit('refresh') : load()">{{ needsListRefresh ? '刷新订单列表' : '重新读取详情' }}</button></p>
    <template v-else-if="detail">
      <dl class="order-facts">
        <div><dt>订单状态</dt><dd>{{ detail.status_label }}</dd></div>
        <div><dt>预约场地</dt><dd>{{ detail.venue_name || '—' }}</dd></div>
        <div><dt>预约时间</dt><dd>{{ detail.booking_time || '—' }}</dd></div>
        <div><dt>订单金额</dt><dd>{{ detail.amount_display === null ? '暂未返回' : `¥${detail.amount_display}` }}</dd></div>
        <div><dt>订单号</dt><dd>{{ detail.order_number || '—' }}</dd></div>
        <div><dt>创建时间</dt><dd>{{ detail.created_at || '—' }}</dd></div>
        <div v-if="detail.paid_at"><dt>官方付款时间</dt><dd>{{ detail.paid_at }}</dd></div>
        <div v-if="detail.use_expires_at"><dt>使用有效期至</dt><dd>{{ detail.use_expires_at }}</dd></div>
      </dl>
      <p v-if="detail.status === '5'" class="order-pending-notice">订单尚未支付。上游将在创建约 5 分钟后自动取消；刷新可查看最新状态。</p>
    </template>
  </section>
</template>

<style scoped>
.order-detail{border-top:1px solid var(--line);padding-top:16px;margin-top:16px;min-width:0}.order-detail header{display:flex;justify-content:space-between;align-items:center;gap:16px}.order-detail h3{margin:0;font-size:15px}.order-detail button{min-height:44px}.order-facts{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:16px;margin:12px 0}.order-facts>div{min-width:0}.order-facts dt{font-size:12px;color:var(--muted);margin-bottom:5px}.order-facts dd{margin:0;font-size:14px;line-height:1.6;overflow-wrap:anywhere}.order-pending-notice{margin:12px 0 0;padding:12px 16px;background:var(--warning-soft);color:var(--ink);border-radius:12px;font-size:13px;line-height:1.7}@media(max-width:600px){.order-facts{grid-template-columns:minmax(0,1fr);gap:12px}}
</style>
