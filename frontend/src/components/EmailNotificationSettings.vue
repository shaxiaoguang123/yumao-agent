<script setup>
import { onMounted, onUnmounted, reactive, ref, watch } from 'vue';

const props = defineProps({
  api: { type: Object, required: true },
  session: { type: Object, required: true },
});

const state = reactive({
  enabled: false,
  reminder_time: '20:00',
  result_time: '08:00',
  recipient: '',
  worker_enabled: false,
});
const testEmailErrors = {
  cloudflare_e_sender_domain_not_available: 'Cloudflare 尚未为发件域启用邮件服务，请完成 Email Sending 域配置。',
  cloudflare_e_sender_not_verified: 'Cloudflare 发件域尚未验证，请先完成域验证。',
  cloudflare_e_internal_server_error: 'Cloudflare 返回暂时性错误，发送结果待核实；请先检查邮箱，再决定是否重试。',
  cloudflare_e_rate_limit_exceeded: 'Cloudflare 邮件服务当前限流，请稍后再检查发送状态。',
  cloudflare_e_daily_limit_exceeded: 'Cloudflare 当日邮件额度已用完，请检查账户计划。',
  cloudflare_e_account_suspended: 'Cloudflare 暂停了此账户的邮件发送，请检查账户状态。',
  cloudflare_message_id_missing: 'Cloudflare 未返回邮件编号，发送结果待核实；请先检查邮箱，再决定是否重试。',
  cloudflare_plan_required: 'Cloudflare Email Sending 报告当前账户需要 Workers Paid；已验证收件地址的免费发送权限仍需确认。',
  cloudflare_sender_domain: 'Cloudflare 发件域未通过验证，请检查 Email Sending 域配置。',
  cloudflare_recipient: 'Cloudflare 未允许此收件地址，请检查已验证的目的地址。',
  cloudflare_rate_limited: 'Cloudflare 邮件服务当前限流，将按退避时间重试。',
  cloudflare_service_unavailable: 'Cloudflare 邮件服务暂时不可用，发送结果待核实；请先检查邮箱。',
};
const version = ref(0);
const status = ref('loading');
const testing = ref(false);
const available = ref(false);
const recent = ref([]);
const error = ref('');
const message = ref('');
let sequence = 0;
let alive = true;

function accept(result) {
  if (result?.available === false) {
    available.value = false;
    return;
  }
  if (!Number.isSafeInteger(result?.version) || typeof result.enabled !== 'boolean'
      || typeof result.reminder_time !== 'string' || typeof result.result_time !== 'string'
      || typeof result.recipient !== 'string' || typeof result.worker_enabled !== 'boolean'
      || !Array.isArray(result.recent)) {
    throw new Error('invalid_email_notification_settings');
  }
  Object.assign(state, {
    enabled: result.enabled,
    reminder_time: result.reminder_time,
    result_time: result.result_time,
    recipient: result.recipient,
    worker_enabled: result.worker_enabled,
  });
  version.value = result.version;
  recent.value = result.recent;
  available.value = true;
}

async function load() {
  const current = ++sequence;
  available.value = false;
  if (props.session?.status !== 'authenticated' || !props.session?.user?.user_id) {
    status.value = 'idle';
    return;
  }
  status.value = 'loading';
  error.value = '';
  message.value = '';
  try {
    const result = await props.api.emailNotificationSettings();
    if (!alive || current !== sequence || props.session?.status !== 'authenticated') return;
    accept(result);
    status.value = 'ready';
  } catch {
    if (!alive || current !== sequence) return;
    status.value = 'error';
    error.value = '邮箱通知设置读取失败，请重试。';
  }
}

async function save() {
  if (status.value !== 'ready' || !available.value) return;
  const current = ++sequence;
  status.value = 'saving';
  error.value = '';
  message.value = '';
  try {
    const result = await props.api.updateEmailNotificationSettings(version.value, {
      enabled: state.enabled,
      reminder_time: state.reminder_time,
    });
    if (!alive || current !== sequence || props.session?.status !== 'authenticated') return;
    accept(result);
    status.value = 'ready';
    message.value = state.enabled ? '邮箱通知已保存。' : '邮箱通知已关闭。';
  } catch (requestError) {
    if (!alive || current !== sequence) return;
    status.value = requestError?.status === 409 ? 'conflict' : 'error';
    error.value = requestError?.status === 409
      ? '设置已在其他页面更新，请重新读取后保存。'
      : '邮箱通知设置未保存，请刷新后核对。';
  }
}

async function sendTest() {
  if (!available.value || testing.value || typeof props.api.sendEmailNotificationTest !== 'function') return;
  testing.value = true;
  error.value = '';
  message.value = '';
  try {
    await props.api.sendEmailNotificationTest();
    message.value = '测试邮件已被 Cloudflare 接受，请查看收件箱和垃圾箱。';
  } catch (requestError) {
    error.value = Object.hasOwn(testEmailErrors, requestError?.code)
      ? testEmailErrors[requestError.code]
      : '测试邮件发送失败，请检查邮箱验证状态或 Cloudflare 发信配置。';
  } finally {
    testing.value = false;
  }
}

function timeText(value) {
  if (!Number.isSafeInteger(value)) return '';
  return new Intl.DateTimeFormat('zh-CN', {
    timeZone: 'Asia/Shanghai', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit', hour12: false,
  }).format(value);
}

watch(() => [props.session?.status, props.session?.user?.user_id,
  props.session?.csrfToken, props.session?.invalidationEpoch], load, { flush: 'sync' });
onMounted(load);
onUnmounted(() => { alive = false; sequence += 1; });
</script>

<template>
  <section v-if="available || status === 'error'" class="email-notification-settings" aria-labelledby="email-notification-title">
    <div class="email-notification-heading">
      <div>
        <h3 id="email-notification-title">邮件通知</h3>
        <p class="muted">按北京时间发送；你名下各 Token 的非空队列分别提醒，执行日 08:00 汇报最终结果。</p>
      </div>
      <label v-if="available" class="email-notification-toggle">
        <input v-model="state.enabled" type="checkbox" :disabled="status === 'saving'" />
        <span>{{ state.enabled ? '已开启' : '已关闭' }}</span>
      </label>
    </div>

    <p v-if="status === 'loading'" class="muted" role="status">正在读取邮箱通知设置…</p>
    <p v-if="error" class="form-error" role="alert">
      {{ error }} <button class="text-button" type="button" @click="load">重新读取</button>
    </p>
    <p v-if="message" class="form-success" role="status">{{ message }}</p>

    <form v-if="available && status !== 'loading' && status !== 'error'" class="email-notification-form" @submit.prevent="save">
      <label class="field">收件邮箱
        <input :value="state.recipient" type="email" readonly aria-readonly="true" />
        <small>此邮箱已在 Cloudflare 验证。</small>
      </label>
      <label class="field">抢票前一晚提醒时间
        <input v-model="state.reminder_time" type="time" min="18:00" max="23:59" :disabled="status === 'saving'" />
        <small>例如目标日期 10/26，默认在抢票日 10/24 的前一晚 20:00 提醒。</small>
      </label>
      <p class="email-notification-result-time">结果邮件固定在抢票日 08:00，包含核验后的实际场地和时段。</p>
      <p v-if="!state.worker_enabled" class="email-notification-warning">执行器未启用，暂时不会产生抢票邮件。</p>
      <div v-if="recent.length" class="email-notification-history" aria-label="最近邮件通知">
        <h4>最近发送</h4>
        <ul>
          <li v-for="item in recent" :key="item.notification_id">
            <span>{{ item.target_date }} · {{ item.kind === 'reminder' ? '抢票提醒' : '结果' }}</span>
            <span>{{ item.status === 'sent' ? 'Cloudflare 已接受' : item.status === 'uncertain' ? '发送结果待核实' : item.status === 'failed' ? '发送失败' : item.status === 'cancelled' ? '已取消' : '排队中' }} · {{ timeText(item.sent_at_utc_ms || item.scheduled_at_utc_ms) }}</span>
          </li>
        </ul>
      </div>
      <div class="email-notification-actions">
        <button class="primary-button" type="submit" :disabled="status === 'saving'">
          {{ status === 'saving' ? '保存中…' : '保存邮件通知设置' }}
        </button>
        <button class="secondary-button" type="button" :disabled="testing" @click="sendTest">
          {{ testing ? '发送中…' : '发送测试邮件' }}
        </button>
        <span v-if="status === 'conflict'">请重新读取后再保存。</span>
      </div>
    </form>
  </section>
</template>

<style scoped>
.email-notification-settings{display:grid;gap:12px;margin-top:14px;padding:16px;border:1px solid var(--line);border-radius:16px;background:var(--page)}
.email-notification-heading{display:flex;align-items:flex-start;justify-content:space-between;gap:12px}
.email-notification-heading h3{margin:0;font-size:15px}
.email-notification-heading p{margin:4px 0 0;font-size:12px}
.email-notification-toggle{display:flex;align-items:center;gap:8px;min-height:44px;flex:none;color:var(--ink);font-size:13px}
.email-notification-toggle input{width:18px;height:18px;accent-color:var(--action)}
.email-notification-form{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px}
.email-notification-form .field input{width:100%;min-height:var(--control-height);padding:10px 12px;border:1px solid var(--line);border-radius:var(--control-radius);background:var(--surface);color:var(--ink)}
.email-notification-result-time{grid-column:1/-1;margin:0;color:var(--muted);font-size:12px}
.email-notification-warning{grid-column:1/-1;margin:0;color:var(--warning);font-size:12px}
.email-notification-warning{grid-column:1/-1;margin:0;color:var(--warning);font-size:12px}
.email-notification-history{grid-column:1/-1;display:grid;gap:6px}
.email-notification-history h4{margin:0;font-size:13px}
.email-notification-history ul{display:grid;gap:6px;margin:0;padding:0;list-style:none}
.email-notification-history li{display:flex;justify-content:space-between;gap:12px;font-size:12px;color:var(--muted)}
.email-notification-actions{grid-column:1/-1;display:flex;align-items:center;gap:12px;flex-wrap:wrap}
.email-notification-actions .primary-button{width:auto}
@media(max-width:640px){.email-notification-form{grid-template-columns:1fr}.email-notification-result-time,.email-notification-history,.email-notification-actions{grid-column:auto}.email-notification-history li{flex-direction:column;gap:2px}}
</style>
