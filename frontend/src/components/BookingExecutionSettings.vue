<script setup>
import { onMounted, onUnmounted, reactive, ref } from 'vue';

const props = defineProps({
  api: { type: Object, required: true },
});

const defaults = () => ({
  reconciliation_time: '00:30',
  clock_calibration_lead_ms: 1000,
  start_offset_ms: 0,
  booking_node_delay_ms: 0,
  booking_by_time_delay_ms: 0,
  get_user_info_delay_ms: 0,
  get_pay_price_delay_ms: 0,
  create_booking_delay_ms: 0,
  open_platform_pay_order_delay_ms: 0,
  payment_verify_delay_ms: 0,
  payment_verify_interval_ms: 3000,
  candidate_interval_ms: 0,
});

const values = reactive(defaults());
const version = ref(0);
const status = ref('loading');
const workerEnabled = ref(false);
const error = ref('');
const message = ref('');
let epoch = 0;
let alive = true;

function applySettings(result) {
  if (!Number.isSafeInteger(result?.version)
      || typeof result.worker_enabled !== 'boolean'
      || !result.settings || typeof result.settings !== 'object' || Array.isArray(result.settings)
      || Object.keys(defaults()).some(key => (
        key === 'reconciliation_time'
          ? typeof result.settings[key] !== 'string'
          : !Number.isSafeInteger(result.settings[key])
      ))) {
    throw new Error('invalid_execution_settings_response');
  }
  Object.assign(values, defaults(), result.settings);
  version.value = result.version;
  workerEnabled.value = result.worker_enabled;
}

async function load() {
  const current = ++epoch;
  status.value = 'loading';
  error.value = '';
  message.value = '';
  try {
    const result = await props.api.executionSettings();
    if (!alive || current !== epoch) return;
    applySettings(result);
    status.value = 'ready';
  } catch {
    if (!alive || current !== epoch) return;
    status.value = 'error';
    error.value = '未能读取当前用户的执行设置。';
  }
}

async function save() {
  if (status.value === 'saving') return;
  const current = ++epoch;
  status.value = 'saving';
  error.value = '';
  message.value = '';
  try {
    const result = await props.api.updateExecutionSettings(version.value, { ...values });
    if (!alive || current !== epoch) return;
    applySettings(result);
    status.value = 'ready';
    message.value = workerEnabled.value
      ? '已保存；你名下所有 Token 会在下次复核时使用这组设置。'
      : '已保存；执行器启用后，你名下所有 Token 会使用这组设置。';
  } catch (requestError) {
    if (!alive || current !== epoch) return;
    status.value = requestError?.status === 409 ? 'conflict' : 'error';
    error.value = requestError?.status === 409
      ? '设置已在其他页面更新，请重新读取后再保存。'
      : '设置未保存，请刷新后核对。';
  }
}

onMounted(load);
onUnmounted(() => { alive = false; epoch += 1; });
</script>

<template>
  <section class="execution-settings" aria-labelledby="execution-settings-title">
    <div class="execution-settings-heading">
      <div class="execution-settings-title">
        <div class="execution-title-line">
          <h2 id="execution-settings-title">自动执行时间</h2>
          <div class="execution-help">
            <button
              class="execution-help-trigger"
              type="button"
              aria-label="查看执行时间和延迟说明"
              aria-describedby="execution-help-content"
            >?</button>
            <div id="execution-help-content" class="execution-help-popover" role="tooltip">
              <strong>延迟发生顺序</strong>
              <ol>
                <li><b>队列复核</b>：在开放日前两天读取真实场地，剔除明确冲突。</li>
                <li><b>时间校准</b>：07:30 前读取服务器时间，修正本机时钟偏差。</li>
                <li><b>开始偏移</b>：从北京时间 07:30 起延后指定毫秒再进入执行。</li>
                <li><b>预约类别</b>：每轮读取类别列表前等待。</li>
                <li><b>场地状态</b>：每个候选重新读取场地状态前等待。</li>
                <li><b>账户信息</b>：读取预约人身份前等待。</li>
                <li><b>获取报价</b>：对已通过校验的候选询价前等待。</li>
                <li><b>创建订单</b>：发送建单请求前等待；预约人数固定填写 5。</li>
                <li><b>发起付款</b>：建单成功后提交支付前等待。</li>
                <li><b>首次查单</b>：支付请求结束后，第一次查询订单前等待。</li>
                <li><b>查单间隔</b>：订单尚未确认时，两次查询之间的等待。</li>
                <li><b>候选间隔</b>：前一个候选未成功时，下一个候选开始前的等待。</li>
              </ol>
            </div>
          </div>
        </div>
        <p>每个用户只设置一次，名下所有 Token 共用；复核时会把当时设置写入各自执行快照。</p>
      </div>
      <span class="execution-worker-state" :class="{ 'is-ready': workerEnabled }">
        {{ workerEnabled ? '执行器已启用' : '执行器未启用' }}
      </span>
    </div>

    <p v-if="error" class="form-error" role="alert">
      {{ error }}
      <button class="text-button" type="button" @click="load">重新读取</button>
    </p>
    <p v-if="message" class="form-success" role="status">{{ message }}</p>

    <form v-if="status !== 'loading' && status !== 'error'" class="execution-settings-form" @submit.prevent="save">
      <label class="field">队列复核时间
        <input v-model="values.reconciliation_time" type="time" min="00:00" max="07:29" :disabled="status === 'saving'" />
        <small>每天只处理第三天，默认 00:30。</small>
      </label>
      <label class="field">执行前校准提前量
        <input v-model.number="values.clock_calibration_lead_ms" type="number" min="0" max="30000" step="100" :disabled="status === 'saving'" />
        <small>毫秒；默认在 07:30 前 1 秒校准。</small>
      </label>
      <label class="field">07:30 后开始偏移
        <input v-model.number="values.start_offset_ms" type="number" min="0" max="60000" step="10" :disabled="status === 'saving'" />
        <small>毫秒；所有 Token 使用同一开始偏移。</small>
      </label>

      <details class="execution-delays">
        <summary>各阶段延迟（毫秒）</summary>
        <div class="execution-delay-grid">
          <label class="field">获取预约类别<input v-model.number="values.booking_node_delay_ms" type="number" min="0" max="60000" step="10" :disabled="status === 'saving'" /></label>
          <label class="field">获取场地状态<input v-model.number="values.booking_by_time_delay_ms" type="number" min="0" max="60000" step="10" :disabled="status === 'saving'" /></label>
          <label class="field">读取账户信息<input v-model.number="values.get_user_info_delay_ms" type="number" min="0" max="60000" step="10" :disabled="status === 'saving'" /></label>
          <label class="field">获取报价<input v-model.number="values.get_pay_price_delay_ms" type="number" min="0" max="60000" step="10" :disabled="status === 'saving'" /></label>
          <label class="field">创建订单<input v-model.number="values.create_booking_delay_ms" type="number" min="0" max="60000" step="10" :disabled="status === 'saving'" /></label>
          <label class="field">发起付款<input v-model.number="values.open_platform_pay_order_delay_ms" name="open_platform_pay_order_delay_ms" type="number" min="0" max="120000" step="10" :disabled="status === 'saving'" /></label>
          <label class="field">首次查询订单<input v-model.number="values.payment_verify_delay_ms" type="number" min="0" max="60000" step="10" :disabled="status === 'saving'" /></label>
          <label class="field">订单查询间隔<input v-model.number="values.payment_verify_interval_ms" name="payment_verify_interval_ms" type="number" min="0" max="60000" step="10" :disabled="status === 'saving'" /></label>
          <label class="field">候选执行间隔<input v-model.number="values.candidate_interval_ms" name="candidate_interval_ms" type="number" min="0" max="60000" step="10" :disabled="status === 'saving'" /></label>
        </div>
      </details>

      <div class="execution-settings-actions">
        <button class="primary-button" type="submit" :disabled="status === 'saving'">
          {{ status === 'saving' ? '保存中…' : '保存执行设置' }}
        </button>
        <span v-if="status === 'conflict'">请重新读取后继续。</span>
      </div>
    </form>
    <p v-else-if="status === 'loading'" class="muted" role="status">正在读取用户级执行设置…</p>
  </section>
</template>

<style scoped>
.execution-settings{margin:0 0 16px;padding:16px;border:1px solid var(--line);border-radius:16px;background:var(--surface)}
.execution-settings-heading{display:flex;justify-content:space-between;align-items:flex-start;gap:16px}
.execution-settings-title{min-width:0}.execution-title-line{display:flex;align-items:center;gap:8px}
.execution-settings-heading h2{margin:0;font-size:18px}.execution-settings-heading p{margin:8px 0 0;color:var(--muted);font-size:13px;line-height:1.6}
.execution-worker-state{flex:none;padding:6px 10px;border-radius:999px;background:var(--warning-soft);color:var(--warning);font-size:12px;white-space:nowrap}.execution-worker-state.is-ready{background:var(--success-soft);color:var(--success)}
.execution-help{position:relative;display:inline-flex}.execution-help-trigger{width:44px;height:44px;padding:0;border:1px solid var(--line);border-radius:50%;background:var(--page);color:var(--brand);font-weight:700;cursor:help}
.execution-help-popover{position:absolute;left:0;top:calc(100% + 8px);z-index:20;display:none;width:min(520px,calc(100vw - 48px));max-height:min(50vh,560px);overflow:auto;padding:16px;border:1px solid var(--line);border-radius:16px;background:var(--surface);box-shadow:var(--shadow);color:var(--ink);font-size:12px;line-height:1.55}
.execution-help:hover .execution-help-popover,.execution-help:focus-within .execution-help-popover{display:block}.execution-help-popover ol{display:grid;gap:8px;margin:8px 0 0;padding-left:20px}.execution-help-popover b{color:var(--brand-dark)}
.execution-settings-form{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px;margin-top:16px}.execution-settings-form .field{gap:8px}.execution-settings-form input{min-width:0}.execution-settings-form small{color:var(--muted);font-size:11px;line-height:1.5;font-weight:400}
.execution-delays{grid-column:1/-1;border-top:1px solid var(--line);padding-top:8px}.execution-delays summary{min-height:var(--control-height);display:flex;align-items:center;cursor:pointer;font-size:14px;color:var(--ink);font-weight:600}.execution-delay-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px;padding:8px 0}
.execution-settings-actions{grid-column:1/-1;display:flex;align-items:center;gap:12px;flex-wrap:wrap}.execution-settings-actions span{font-size:12px;color:var(--warning)}
@media(max-width:800px){.execution-settings-form,.execution-delay-grid{grid-template-columns:repeat(2,minmax(0,1fr))}}
@media(max-width:560px){.execution-settings{padding:16px 12px}.execution-settings-heading{display:grid}.execution-worker-state{justify-self:start}.execution-settings-form,.execution-delay-grid{grid-template-columns:minmax(0,1fr)}.execution-settings-actions .primary-button{width:100%}}
@media(max-width:734px){.execution-help-popover{position:fixed;left:16px;right:16px;top:auto;bottom:max(16px,env(safe-area-inset-bottom));width:auto;max-height:65dvh}}
</style>
