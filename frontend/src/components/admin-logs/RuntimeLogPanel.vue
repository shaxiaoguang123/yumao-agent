<script setup>
import { computed, inject, onBeforeUnmount, shallowRef, watch } from 'vue';
import { logTime } from '../../utils/runtimeLogs.js';
import RuntimeLogFilters from './RuntimeLogFilters.vue';
import RuntimeLogList from './RuntimeLogList.vue';
import RuntimeLogDetail from './RuntimeLogDetail.vue';
const api = inject('diagnosticsApi');
const session = inject('sessionStore');
const permitted = computed(() => session?.status === 'authenticated' && session.user?.role === 'admin');
const events = shallowRef([]);
const status = shallowRef('loading');
const collection = shallowRef(null);
const collectors = shallowRef([]);
const queriedAt = shallowRef(null);
const cursor = shallowRef(null);
const detail = shallowRef(null);
const selectedId = shallowRef(null);
const detailStatus = shallowRef('idle');
const message = shallowRef('');
let filters = { hours: '24' };
let until;
let since;
let listGeneration = 0;
let detailGeneration = 0;
let listController;
let detailController;
function closeDetail() { detailGeneration += 1; detailController?.abort(); detail.value = null; selectedId.value = null; detailStatus.value = 'idle'; }
async function load(next = filters, more = false) {
  const version = ++listGeneration;
  listController?.abort();
  if (!permitted.value) { events.value = []; collection.value = null; closeDetail(); return; }
  if (!more) { filters = next; events.value = []; closeDetail(); }
  status.value = 'loading';
  message.value = '';
  listController = new AbortController();
  const { hours, ...exact } = filters;
  try {
    const result = await api.logs({ ...exact, hours: Number(hours), limit: 50, ...(more ? { since, until, before: cursor.value } : {}) }, { signal: listController.signal });
    if (version !== listGeneration) return;
    if (!Array.isArray(result?.events) || !result.collection) throw new Error('invalid_log_response');
    events.value = more ? [...events.value, ...result.events] : result.events;
    cursor.value = result.next_cursor;
    collection.value = result.collection;
    collectors.value = result.collectors || [];
    queriedAt.value = result.queried_at_utc_ms;
    since = result.window?.since;
    until = result.window?.until;
    status.value = 'ready';
  } catch (error) {
    if (version !== listGeneration) return;
    status.value = 'error';
    collection.value = null;
    if (error.status === 401 || error.status === 403) { events.value = []; cursor.value = null; closeDetail(); }
    message.value = error.status === 403 ? '管理员权限已失效，请重新登录。' : error.status === 400 ? '筛选条件无效，请检查编号和时间范围。' : '运行日志暂时不可用，请重试。';
    if (error.requestId) message.value += ` 请求编号：${error.requestId}`;
  }
}
async function select(id) {
  const version = ++detailGeneration;
  detailController?.abort();
  detailController = new AbortController();
  selectedId.value = id;
  detail.value = null;
  detailStatus.value = 'loading';
  try {
    const result = await api.detail(id, { signal: detailController.signal });
    if (version !== detailGeneration) return;
    if (!result?.event || !Array.isArray(result.related)) throw new Error('invalid_log_detail');
    detail.value = result;
    detailStatus.value = 'ready';
  } catch {
    if (version !== detailGeneration) return;
    detailStatus.value = 'error';
  }
}
const processStates = computed(() => collectors.value.map(item => ({ ...item, label: item.role === 'worker' ? 'Worker 采集器' : 'Web 采集器', stale: (queriedAt.value || Date.now()) - item.seen_at_utc_ms > 120000 })));
const visibleCounts = computed(() => ({ error: events.value.filter(item => item.level === 'error').length, warning: events.value.filter(item => item.level === 'warning').length }));
watch([permitted, () => session?.user?.user_id], () => load(), { immediate: true });
onBeforeUnmount(() => { listGeneration += 1; listController?.abort(); closeDetail(); });
</script>
<template>
  <div v-if="permitted" class="runtime-log-workspace">
    <section class="panel log-controls"><RuntimeLogFilters :busy="status === 'loading'" @apply="value => load(value)" /></section>
    <section v-if="collection" class="panel collection-health" aria-label="日志采集状态"><div class="collection-heading"><strong>{{ collection.state === 'ready' ? '日志采集已就绪' : '日志采集需要关注' }}</strong><span>保留 {{ collection.retention_days }} 天 · 写入为异步，最新事件可能稍有延迟</span></div><div class="collector-facts"><span>当前 Web 队列 {{ collection.queue_depth }}</span><span :class="{ 'collection-warning': collection.dropped_events || collection.failed_events }">丢弃 {{ collection.dropped_events }} · 写入失败 {{ collection.failed_events }}</span></div><ul><li v-for="item in processStates" :key="`${item.role}-${item.pid}`"><strong>{{ item.label }} · PID {{ item.pid }}</strong><span>{{ item.stale ? '近期未收到心跳' : '近期已收到心跳' }} · {{ logTime(item.seen_at_utc_ms) }}</span><span>丢弃 {{ item.dropped_events }} · 写入失败 {{ item.failed_events }}</span></li></ul><p class="muted">心跳仅代表日志采集器状态；执行结果请核对具体任务记录。</p></section>
    <div class="log-results-heading"><p>已载入 <strong>{{ events.length }}</strong> 条 · 错误 {{ visibleCounts.error }} · 警告 {{ visibleCounts.warning }}<span v-if="queriedAt"> · 查询于 {{ logTime(queriedAt) }}</span></p><button class="secondary-button" type="button" :disabled="status === 'loading'" @click="load()">刷新日志</button></div>
    <p v-if="message" class="form-error log-message" role="alert">{{ message }}</p>
    <p v-if="status === 'loading'" class="muted" role="status">正在读取运行日志…</p>
    <p v-else-if="status === 'ready' && !events.length" class="panel log-empty" role="status">当前筛选范围内没有已采集的记录。可以调整级别、模块或时间范围。</p>
    <RuntimeLogList :events="events" :selected-id="selectedId" @select="select">
      <template #detail="{ event }">
        <p v-if="selectedId === event.event_id && detailStatus === 'loading'" class="log-detail-state muted" role="status">正在读取日志详情…</p>
        <p v-else-if="selectedId === event.event_id && detailStatus === 'error'" class="log-detail-state form-error" role="alert">详情暂时不可用，请重新选择。</p>
        <RuntimeLogDetail v-else-if="selectedId === event.event_id && detail" :detail="detail" @close="closeDetail" />
      </template>
    </RuntimeLogList>
    <button v-if="cursor && status !== 'error'" class="secondary-button load-logs" type="button" :disabled="status === 'loading'" @click="load(filters, true)">加载更早日志</button>
  </div>
</template>
<style scoped>
.runtime-log-workspace{display:grid;gap:16px;min-width:0}.log-controls{padding:20px}.collection-health{padding:18px;display:grid;gap:10px;min-width:0}.collection-heading,.collector-facts{display:flex;justify-content:space-between;gap:10px;flex-wrap:wrap}.collection-heading strong{font-size:13px}.collection-heading span,.collector-facts,.collection-health p{font-size:12px;color:var(--muted)}.collection-health p{margin:0}.collection-health ul{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px;list-style:none;margin:0;padding:0}.collection-health li{display:grid;gap:5px;padding:12px;background:var(--page);border-radius:10px;min-width:0;font-size:11px;overflow-wrap:anywhere;color:var(--muted)}.collection-health li strong{font-weight:500;color:var(--ink)}.collection-warning{color:var(--danger)}.log-results-heading{display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap}.log-results-heading p{margin:0;font-size:12px;color:var(--muted)}.log-message{overflow-wrap:anywhere}.log-detail-state{grid-column:1/-1;margin:0;padding:8px;border-radius:8px;background:var(--surface);font-size:12px}.log-empty{padding:24px;color:var(--muted);font-size:13px}.load-logs{justify-self:center;min-height:44px}@media(max-width:650px){.log-controls{padding:16px}.collection-health ul{grid-template-columns:minmax(0,1fr)}.log-results-heading button{min-height:44px}}
</style>
