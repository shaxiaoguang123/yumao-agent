<script setup>
import { computed, inject, onBeforeUnmount, shallowRef, watch } from 'vue';
import { RouterLink } from 'vue-router';
import ActivityBars from './ActivityBars.vue';
import { moduleLabel } from '../../utils/runtimeLogs.js';
const props = defineProps({ system: Boolean });
const api = inject('diagnosticsApi', null);
const session = inject('sessionStore', null);
const data = shallowRef(null);
const status = shallowRef('loading');
const errorId = shallowRef('');
const permitted = computed(() => api && session?.status === 'authenticated' && (!props.system || session.user?.role === 'admin'));
let controller;
let generation = 0;
async function load() {
  const version = ++generation;
  controller?.abort();
  if (!permitted.value) { data.value = null; return; }
  controller = new AbortController();
  status.value = 'loading';
  errorId.value = '';
  try {
    const result = await api[props.system ? 'system' : 'overview']({ signal: controller.signal });
    if (version !== generation) return;
    if (result?.scope !== (props.system ? 'system' : 'personal') || !Array.isArray(result?.execution?.trend) || !result?.queues || !result?.credentials) throw new Error('invalid_metrics');
    data.value = result;
    status.value = 'ready';
  } catch (error) {
    if (version !== generation) return;
    status.value = 'error';
    data.value = null;
    errorId.value = error.requestId || '';
  }
}
watch([permitted, () => session?.user?.user_id], load, { immediate: true });
onBeforeUnmount(() => { generation += 1; controller?.abort(); });
const cards = computed(() => data.value ? [
  { label: props.system ? '全站未来队列' : '未来队列', value: data.value.queues.upcoming, note: '今天起，当前版本非空队列' },
  { label: '候选场次', value: data.value.queues.candidates, note: `2 小时 ${data.value.queues.two_hour} · 1 小时 ${data.value.queues.one_hour}` },
  { label: '近七天执行成功', value: data.value.execution.states.succeeded, note: `共 ${data.value.execution.runs} 次复核任务` },
  { label: '需要处理', value: data.value.execution.states.needs_attention, note: '执行结果需核对的任务' },
] : []);
const runtime = computed(() => data.value?.diagnostics);
const moduleBars = computed(() => {
  const rows = runtime.value?.modules || [];
  const maximum = Math.max(1, ...rows.map(row => row.count));
  return rows.map(row => ({ ...row, label: moduleLabel(row.module), width: `${row.count / maximum * 100}%` }));
});
const updatedAt = computed(() => data.value ? new Intl.DateTimeFormat('zh-CN', { hour: '2-digit', minute: '2-digit', second: '2-digit', timeZone: data.value.timezone }).format(data.value.generated_at_utc_ms) : '');
</script>
<template>
  <section v-if="permitted" class="activity-overview" :aria-label="system ? '全站运行概览' : '我的预约概览'" :aria-busy="status === 'loading'">
    <div class="activity-heading"><div><p class="eyebrow">{{ system ? 'SYSTEM ACTIVITY' : 'MY ACTIVITY' }}</p><h2>{{ system ? '全站运行概览' : '我的预约概览' }}</h2></div><div class="activity-controls"><small v-if="updatedAt">更新于 {{ updatedAt }}</small><button class="secondary-button" type="button" :disabled="status === 'loading'" @click="load">刷新指标</button></div></div>
    <p v-if="status === 'loading'" class="muted" role="status">正在读取运行指标…</p>
    <p v-else-if="status === 'error'" class="form-error" role="alert">指标暂时不可用，请重试。<span v-if="errorId">请求编号：{{ errorId }}</span></p>
    <template v-else-if="data">
      <div class="activity-cards"><article v-for="card in cards" :key="card.label" class="panel activity-card"><span>{{ card.label }}</span><strong>{{ card.value }}</strong><small>{{ card.note }}</small></article></div>
      <div class="activity-charts">
        <section class="panel activity-plot"><h3>近七天执行结果</h3><p class="muted plot-description">按复核任务创建日期汇总当前状态；成功依据执行器确认结果。</p><ActivityBars :rows="data.execution.trend" /><p v-if="!data.execution.runs" class="chart-empty">还没有执行记录。保存队列不会立即产生执行记录。</p></section>
        <section v-if="system" class="panel activity-plot"><div class="runtime-heading"><h3>近七天异常趋势</h3><RouterLink :to="{ name: 'admin-logs' }" class="action-link">查看运行日志</RouterLink></div><template v-if="runtime?.available"><p class="muted plot-description">已保留的日志事件；同一次请求可能包含多个诊断事件。</p><ActivityBars :rows="runtime.trend" kind="errors" /><dl class="runtime-numbers"><div><dt>近 24h 业务请求</dt><dd>{{ runtime.request_count }}</dd></div><div><dt>5xx 请求</dt><dd>{{ runtime.failed_requests }}</dd></div><div><dt>平均耗时</dt><dd>{{ runtime.mean_request_ms === null ? '—' : `${runtime.mean_request_ms} ms` }}</dd></div></dl><p v-if="runtime.collection.state !== 'ready' || runtime.collection.dropped_events || runtime.collection.failed_events" class="form-error" role="status">采集存在延迟或丢失，请查看日志页的采集状态。</p></template><p v-else class="muted" role="status">运行日志尚未就绪或采集未启用；业务统计仍可查看。</p></section>
        <section v-else class="panel activity-plot queue-balance"><h3>队列准备情况</h3><dl><div><dt>尚未到开抢时间</dt><dd>{{ data.queues.before_opening }} 份</dd></div><div><dt>近七天待执行 / 执行中</dt><dd>{{ data.execution.pending }} 次</dd></div><div><dt>已启用凭据</dt><dd>{{ data.credentials.enabled }} / {{ data.credentials.total }}</dd></div></dl><p class="muted plot-description">排期还取决于有效凭据、支付密码和执行器配置。候选数量不代表已预约场次。</p></section>
      </div>
      <section v-if="system && runtime?.available" class="panel activity-plot module-distribution" aria-label="近24小时异常模块分布"><h3>近 24 小时异常模块分布</h3><ul v-if="moduleBars.length"><li v-for="item in moduleBars" :key="item.module"><span>{{ item.label }}</span><div aria-hidden="true"><i :style="{ width: item.width }" /></div><strong>{{ item.count }}</strong></li></ul><p v-else class="muted plot-description">已保留的日志中没有警告或错误事件。</p></section>
    </template>
  </section>
</template>
<style scoped>
.module-distribution ul{list-style:none;padding:0;margin:16px 0 0;display:grid;gap:12px}.module-distribution li{display:grid;grid-template-columns:96px minmax(0,1fr) 36px;align-items:center;gap:12px;font-size:12px}.module-distribution li>div{height:8px;background:var(--page);border-radius:4px;overflow:hidden}.module-distribution i{display:block;height:100%;background:var(--brand);border-radius:4px}.module-distribution strong{text-align:right;font-weight:500;font-variant-numeric:tabular-nums}
.activity-overview{display:grid;gap:16px;min-width:0;margin-top:24px}.activity-heading,.activity-controls,.runtime-heading{display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap}.activity-heading h2{font-size:19px;margin:4px 0 0}.activity-heading .eyebrow{margin:0}.activity-controls small{font-size:12px;color:var(--muted)}.activity-controls button{min-height:36px}.activity-cards{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px}.activity-card{display:grid;gap:8px;padding:18px;min-width:0}.activity-card span,.activity-card small{font-size:12px;color:var(--muted);overflow-wrap:anywhere}.activity-card strong{font-size:28px;font-variant-numeric:tabular-nums;line-height:1.2}.activity-charts{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:16px}.activity-plot{padding:20px;min-width:0}.activity-plot h3{font-size:15px;margin:0 0 8px}.plot-description{font-size:12px;line-height:1.7;margin:8px 0 16px}.chart-empty{font-size:12px;color:var(--muted);margin:12px 0 0}.queue-balance dl{display:grid;gap:14px;margin:24px 0}.queue-balance dl>div{display:flex;align-items:center;justify-content:space-between;gap:12px;border-bottom:1px solid var(--line);padding-bottom:12px}.queue-balance dt,.runtime-numbers dt{font-size:12px;color:var(--muted)}.queue-balance dd{font-size:18px;font-weight:600;margin:0}.runtime-numbers{display:flex;flex-wrap:wrap;justify-content:space-between;gap:12px;margin:16px 0 0}.runtime-numbers dd{margin:4px 0 0;font-size:15px;font-variant-numeric:tabular-nums}.runtime-heading a{font-size:12px}.form-error span{display:block;overflow-wrap:anywhere}@media(max-width:850px){.activity-cards{grid-template-columns:repeat(2,minmax(0,1fr))}.activity-charts{grid-template-columns:minmax(0,1fr)}}@media(max-width:420px){.activity-card{padding:14px}.activity-plot{padding:16px}.activity-controls{width:100%}}
</style>
