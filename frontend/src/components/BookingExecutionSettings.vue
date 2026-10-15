<script setup>
import { onUnmounted, reactive, ref, watch } from 'vue';
import { RouterLink } from 'vue-router';

const props = defineProps({
  api: { type: Object, required: true },
  credentialId: { type: String, default: '' },
});

const defaults = () => ({
  reconciliation_time: '00:30',
  clock_calibration_lead_ms: 1000,
  start_offset_ms: 0,
  booking_node_delay_ms: 0,
  booking_by_time_delay_ms: 0,
  get_user_info_delay_ms: 0,
  get_children_delay_ms: 0,
  get_pay_price_delay_ms: 0,
  create_booking_delay_ms: 0,
  open_platform_pay_order_delay_ms: 0,
  payment_verify_delay_ms: 0,
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
  if (result?.credential_id !== props.credentialId
      || !Number.isSafeInteger(result.version)
      || typeof result.worker_enabled !== 'boolean'
      || !result.settings || typeof result.settings !== 'object' || Array.isArray(result.settings)
      || Object.keys(defaults()).some(key => !Number.isSafeInteger(result.settings[key])
        && key !== 'reconciliation_time')) {
    throw new Error('invalid_execution_settings_response');
  }
  if (typeof result.settings.reconciliation_time !== 'string') {
    throw new Error('invalid_execution_settings_response');
  }
  Object.assign(values, defaults(), result.settings);
  version.value = result.version;
  workerEnabled.value = result.worker_enabled;
}

async function load() {
  const current = ++epoch;
  status.value = props.credentialId ? 'loading' : 'idle';
  error.value = '';
  message.value = '';
  if (!props.credentialId) {
    Object.assign(values, defaults());
    version.value = 0;
    workerEnabled.value = false;
    return;
  }
  try {
    const result = await props.api.executionSettings(props.credentialId);
    if (!alive || current !== epoch) return;
    applySettings(result);
    status.value = 'ready';
  } catch {
    if (!alive || current !== epoch) return;
    status.value = 'error';
    error.value = '未能读取此 Token 的执行设置。';
  }
}

async function save() {
  if (status.value === 'saving') return;
  const current = ++epoch;
  status.value = 'saving';
  error.value = '';
  message.value = '';
  try {
    const result = await props.api.updateExecutionSettings(
      props.credentialId,
      version.value,
      { ...values },
    );
    if (!alive || current !== epoch) return;
    applySettings(result);
    status.value = 'ready';
    message.value = workerEnabled.value
      ? '已保存；非空队列会按这些设置处理并执行。'
      : '已保存；执行器启用后，非空队列会按这些设置处理并执行。';
  } catch (requestError) {
    if (!alive || current !== epoch) return;
    status.value = requestError?.status === 409 ? 'conflict' : 'error';
    error.value = requestError?.status === 409
      ? '设置已在其他页面更新，请重新读取后再保存。'
      : '设置未保存，请刷新后核对。';
  }
}

watch(() => props.credentialId, () => { void load(); }, { immediate: true, flush: 'sync' });
onUnmounted(() => { alive = false; epoch += 1; });
</script>

<template>
  <section class="execution-settings" aria-labelledby="execution-settings-title">
    <div class="execution-settings-heading">
      <div>
        <h2 id="execution-settings-title">自动执行时间</h2>
        <p>此 Token 的计划独立保存。候选队列非空即授权预约并自动付款；设置在复核时写入快照。</p>
      </div>
      <span class="execution-worker-state" :class="{ 'is-ready': workerEnabled }">
        {{ workerEnabled ? '执行器已启用' : '执行器未启用' }}
      </span>
    </div>

    <p v-if="!credentialId" class="muted execution-no-credential">在计划页上方选择一个预约 Token 后，这里会显示该 Token 独立的执行时间设置。没有 Token 时请先前往 <RouterLink to="/credentials">预约凭据</RouterLink> 添加。</p>
    <p v-if="error" class="form-error" role="alert">{{ error }} <button v-if="status === 'error'" class="text-button" type="button" @click="load">重新读取</button></p>
    <p v-if="message" class="form-success" role="status">{{ message }}</p>

    <form v-if="credentialId && status !== 'loading' && status !== 'error'" class="execution-settings-form" @submit.prevent="save">
      <label class="field">队列复核时间<input v-model="values.reconciliation_time" type="time" min="00:00" max="07:29" :disabled="status === 'saving'" /><small>每天只处理第三天；默认 00:30。</small></label>
      <label class="field">执行前校准提前量<input v-model.number="values.clock_calibration_lead_ms" type="number" min="0" max="30000" step="100" :disabled="status === 'saving'" /><small>毫秒；默认在 07:30 前 1 秒校准。</small></label>
      <label class="field">07:30 后开始偏移<input v-model.number="values.start_offset_ms" type="number" min="0" max="60000" step="10" :disabled="status === 'saving'" /><small>毫秒；不同 Token 可错开启动。</small></label>
      <details class="execution-delays">
        <summary>阶段延迟（毫秒）</summary>
        <div class="execution-delay-grid">
          <label class="field">获取预约类别<input v-model.number="values.booking_node_delay_ms" type="number" min="0" max="60000" step="10" :disabled="status === 'saving'" /></label>
          <label class="field">获取场地状态<input v-model.number="values.booking_by_time_delay_ms" type="number" min="0" max="60000" step="10" :disabled="status === 'saving'" /></label>
          <label class="field">读取账户信息<input v-model.number="values.get_user_info_delay_ms" type="number" min="0" max="60000" step="10" :disabled="status === 'saving'" /></label>
          <label class="field">读取预约人数<input v-model.number="values.get_children_delay_ms" type="number" min="0" max="60000" step="10" :disabled="status === 'saving'" /></label>
          <label class="field">获取报价<input v-model.number="values.get_pay_price_delay_ms" type="number" min="0" max="60000" step="10" :disabled="status === 'saving'" /></label>
          <label class="field">创建订单<input v-model.number="values.create_booking_delay_ms" type="number" min="0" max="60000" step="10" :disabled="status === 'saving'" /></label>
          <label class="field">发起付款<input v-model.number="values.open_platform_pay_order_delay_ms" type="number" min="0" max="60000" step="10" :disabled="status === 'saving'" /></label>
          <label class="field">付款结果查询<input v-model.number="values.payment_verify_delay_ms" type="number" min="0" max="60000" step="10" :disabled="status === 'saving'" /></label>
        </div>
      </details>
      <div class="execution-settings-actions">
        <button class="primary-button" type="submit" :disabled="status === 'saving'">{{ status === 'saving' ? '保存中…' : '保存执行设置' }}</button>
        <span v-if="status === 'conflict'">请重新读取后继续。</span>
      </div>
    </form>
    <p v-else-if="credentialId && status === 'loading'" class="muted" role="status">正在读取 Token 执行设置…</p>
  </section>
</template>

<style scoped>
.execution-settings{margin:0 0 12px;padding:16px;border:1px solid var(--line);border-radius:12px;background:var(--surface)}
.execution-settings-heading{display:flex;justify-content:space-between;align-items:flex-start;gap:12px}
.execution-settings-heading h2{margin:0;font-size:17px}.execution-settings-heading p{margin:5px 0 0;color:var(--muted);font-size:12px;line-height:1.55}.execution-no-credential{margin:12px 0 0;font-size:13px}
.execution-worker-state{flex:none;padding:5px 8px;border-radius:6px;background:var(--warning-soft);color:var(--warning);font-size:11px;white-space:nowrap}.execution-worker-state.is-ready{background:var(--brand-soft);color:var(--brand-dark)}
.execution-settings-form{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,170px),1fr));gap:12px;margin-top:14px}.execution-settings-form .field{font-size:12px;gap:5px}.execution-settings-form input{min-width:0;min-height:44px;padding:8px 10px;font-size:14px}.execution-settings-form small{color:var(--muted);font-size:11px;line-height:1.5}
.execution-delays{grid-column:1/-1;border-top:1px solid var(--line);padding-top:8px}.execution-delays summary{min-height:44px;display:flex;align-items:center;cursor:pointer;font-size:13px;color:var(--ink)}.execution-delay-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,140px),1fr));gap:10px;padding:8px 0}
.execution-settings-actions{grid-column:1/-1;display:flex;align-items:center;gap:10px}.execution-settings-actions button{min-height:44px;font-size:13px}.execution-settings-actions span{font-size:12px;color:var(--warning)}
</style>
