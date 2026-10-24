<script setup>
import { onUnmounted, ref, watch } from 'vue';
import ManualQueuePreview from './ManualQueuePreview.vue';
import { executionStateLabels } from '../../utils/executionStatus.js';

const props = defineProps({
  api: { type: Object, required: true },
  credentialId: { type: String, required: true },
  targetDate: { type: String, required: true },
  session: { type: Object, required: true },
  sourcePlanId: { type: String, default: '' },
  refreshKey: { type: Number, default: 0 },
  active: { type: Boolean, default: true },
});
const emit = defineEmits(['status-change']);

const run = ref(null);
const workerEnabled = ref(false);
const state = ref('idle');
let alive = true;
let sequence = 0;

const stageLabels = {
  reconcile_booking_node: '复核预约类别',
  reconcile_booking_by_time: '00:30 场地查询',
  booking_node_list: '刷新预约类别',
  booking_by_time: '执行前场地查询',
  fresh_availability_check: '候选状态校验',
  get_user_info: '读取预约账户',
  clock_calibration: '北京时间校准',
  get_children: '读取预约人数',
  get_pay_price: '获取报价',
  create_booking: '创建订单',
  open_platform_pay_order: '发起付款',
  payment_verification: '核验付款结果',
  payment_outcome: '付款结果',
};

function timeText(value) {
  if (!Number.isSafeInteger(value)) return '—';
  return new Intl.DateTimeFormat('zh-CN', { hour: '2-digit', minute: '2-digit', second: '2-digit' }).format(value);
}

async function load() {
  const current = ++sequence;
  updateStatus('loading');
  if (!props.active || props.session?.status !== 'authenticated' || typeof props.api.executionQueue !== 'function'
      || !props.credentialId || !props.targetDate) {
    updateStatus('unavailable');
    return;
  }
  try {
    const result = await props.api.executionQueue(props.targetDate, props.credentialId);
    if (!alive || current !== sequence) return;
    if (result?.worker_enabled !== true && result?.worker_enabled !== false) throw new Error('invalid_response');
    if (result.run !== null && (result.run?.target_date !== props.targetDate
        || !Array.isArray(result.run.candidates) || !Array.isArray(result.run.stages)
        || (props.sourcePlanId && (result.run.source_plan_id !== props.sourcePlanId
          || !Number.isSafeInteger(result.run.source_version) || result.run.source_version < 1
          || typeof result.run.source_revision_id !== 'string' || !result.run.source_revision_id)))) throw new Error('invalid_response');
    updateStatus('ready', result);
  } catch {
    if (!alive || current !== sequence) return;
    updateStatus('error');
  }
}

function updateStatus(status, result = null) {
  run.value = result?.run ?? null;
  workerEnabled.value = result?.worker_enabled === true;
  state.value = status;
  emit('status-change', { status, run: run.value, workerEnabled: workerEnabled.value });
}

watch(() => [props.credentialId, props.targetDate, props.sourcePlanId, props.refreshKey, props.active,
  props.session?.user?.user_id, props.session?.status, props.session?.csrfToken,
  props.session?.invalidationEpoch], () => { void load(); }, { immediate: true, flush: 'sync' });
onUnmounted(() => { alive = false; sequence += 1; });
</script>

<template>
  <details v-if="state !== 'unavailable'" class="execution-snapshot" :data-testid="`execution-snapshot-${targetDate}`">
    <summary>
      <span>执行队列</span>
      <span v-if="state === 'loading'">读取中…</span>
      <span v-else-if="state === 'error'">状态读取失败</span>
      <span v-else-if="run">{{ executionStateLabels[run.state] || '状态未知' }} · {{ run.candidate_count }} 项</span>
      <span v-else>{{ workerEnabled ? '等待复核' : '执行器未启用' }}</span>
    </summary>
    <div v-if="state === 'error'" class="muted"><button type="button" class="text-button" @click="load">重新读取</button></div>
    <div v-else-if="run" class="execution-snapshot-body">
      <p class="muted">来自保存队列 v{{ run.source_version }} · 保留 {{ run.reconciliation.retained_candidate_count || 0 }} 项</p>
      <div v-if="Object.keys(run.reconciliation.discarded_candidate_counts||{}).length" class="execution-filter-summary">
        <span v-for="(count,reason) in run.reconciliation.discarded_candidate_counts" :key="reason">{{ reason }}：{{ count }}</span>
      </div>
      <ManualQueuePreview v-if="run.candidates.length" :entries="run.candidates" readonly />
      <ol v-if="run.stages.length" class="execution-stage-list">
        <li v-for="(stage,index) in run.stages" :key="`${stage.round_number}-${stage.candidate_index}-${stage.stage_key}-${index}`">
          <span>{{ stageLabels[stage.stage_key] || '执行阶段' }}<small v-if="stage.round_number"> · 第 {{ stage.round_number }} 轮</small></span>
          <span>{{ timeText(stage.started_at_utc_ms) }}–{{ timeText(stage.completed_at_utc_ms) }} · {{ stage.elapsed_ms }} ms</span>
        </li>
      </ol>
      <p v-if="!run.candidates.length" class="muted">此日期没有生成可执行场地。</p>
    </div>
    <p v-else class="muted">复核时间到后，执行器会按第三天的真实场地生成独立快照。</p>
  </details>
</template>

<style scoped>
.execution-snapshot{margin-top:8px;border-top:1px solid var(--line);padding-top:8px;color:var(--muted);font-size:12px}
.execution-snapshot>summary{display:flex;align-items:center;gap:8px;min-height:var(--control-height);cursor:pointer;list-style:none}.execution-snapshot>summary::-webkit-details-marker{display:none}.execution-snapshot>summary span:last-child{margin-left:auto}
.execution-snapshot-body{display:grid;gap:8px;padding:8px 0 8px}.execution-snapshot-body>p{margin:0;font-size:12px}.execution-filter-summary{display:flex;flex-wrap:wrap;gap:8px 8px;font-size:12px}.execution-stage-list{display:grid;gap:8px;margin:0;padding:0;list-style:none;font-size:12px}.execution-stage-list li{display:flex;justify-content:space-between;gap:8px}.execution-stage-list small{color:var(--muted)}
</style>
