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
    <details v-if="collection" class="collection-health disclosure-panel" aria-label="日志采集状态" :open="collection.state !== 'ready' || Boolean(collection.dropped_events || collection.failed_events) || processStates.some(item => item.stale || item.dropped_events || item.failed_events)"><summary><span><i class="availability-dot" />{{ collection.state === 'ready' ? '日志采集已就绪' : '日志采集需要关注' }}</span><small>队列 {{ collection.queue_depth }} · 丢失 {{ collection.dropped_events }}</small></summary><div class="disclosure-body"><div class="collection-heading"><strong>{{ collection.state === 'ready' ? '日志采集已就绪' : '日志采集需要关注' }}</strong><span>保留 {{ collection.retention_days }} 天 · 写入为异步，最新事件可能稍有延迟</span></div><div class="collector-facts"><span>当前 Web 队列 {{ collection.queue_depth }}</span><span :class="{ 'collection-warning': collection.dropped_events || collection.failed_events }">丢弃 {{ collection.dropped_events }} · 写入失败 {{ collection.failed_events }}</span></div><ul><li v-for="item in processStates" :key="`${item.role}-${item.pid}`"><strong>{{ item.label }} · PID {{ item.pid }}</strong><span>{{ item.stale ? '近期未收到心跳' : '近期已收到心跳' }} · {{ logTime(item.seen_at_utc_ms) }}</span><span>丢弃 {{ item.dropped_events }} · 写入失败 {{ item.failed_events }}</span></li></ul><p class="muted">心跳仅反映日志采集；预约结果请核对任务记录。</p></div></details>
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
.runtime-log-workspace { display:grid; gap:12px; min-width:0; }
.log-controls { padding:16px; }
.collection-health { min-width:0; }
.collection-health > summary { min-height:48px; }
.collection-health > summary span { min-width:0; font-size:12px; }
.collection-health > summary small { font-size:11px; }
.collection-heading,.collector-facts { display:flex; justify-content:space-between; flex-wrap:wrap; gap:8px; font-size:12px; }
.collection-heading span,.collector-facts,.collection-health p { color:var(--muted); font-size:12px; }
.collection-health p { margin:10px 0 0; }
.collection-health ul { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:8px; margin:12px 0 0; padding:0; list-style:none; }
.collection-health li { display:grid; gap:4px; min-width:0; padding:10px; border-radius:12px; background:var(--page); font-size:12px; color:var(--muted); overflow-wrap:anywhere; }
.collection-warning { color:var(--danger); }
.log-results-heading { display:flex; align-items:center; justify-content:space-between; gap:8px; }
.log-results-heading p { margin:0; color:var(--muted); font-size:12px; }
.log-results-heading p > span { display:none; }
.log-results-heading button { flex:none; }
.log-message { overflow-wrap:anywhere; }
.log-detail-state { grid-column:1/-1; margin:0; padding:8px; font-size:12px; }
.log-empty { padding:20px; color:var(--muted); font-size:13px; }
.load-logs { justify-self:center; }
@media(max-width:600px) { .collection-health > summary { padding-inline:12px; gap:6px; } .collection-health ul { grid-template-columns:minmax(0,1fr); } }
</style>
