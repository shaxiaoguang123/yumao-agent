<script setup>
import { computed } from 'vue';
import AppIcon from '../AppIcon.vue';

const props = defineProps({
  message: { type: String, default: '' },
  answer: { type: String, default: '' },
  mode: { type: String, default: 'queue' },
  targetId: { type: String, default: '' },
  plans: { type: Array, default: () => [] },
  status: { type: String, default: 'idle' },
  businessDate: { type: String, default: '' },
  followUp: Boolean,
  busy: Boolean,
  blocked: Boolean,
  sendBlocked: Boolean,
  suppressed: Boolean,
  locked: Boolean,
  selectionDisabled: Boolean,
});
const emit = defineEmits(['update:message', 'update:answer', 'update:target-id', 'send', 'edit-request']);

const fields = [
  { key: 'date', label: '日期', text: '日期：' },
  { key: 'windows', label: '2小时时段', text: '2小时时段：' },
  { key: 'courts', label: '场地', text: '场地：' },
  { key: 'one', label: '1小时备选', text: '1小时备选：' },
];
const timeOptions = (duration) => Array.from({ length: 22 - 9 - duration + 1 }, (_, index) => {
  const start = 9 + index;
  return `${String(start).padStart(2, '0')}-${String(start + duration).padStart(2, '0')}`;
});
const windows2 = timeOptions(2), windows1 = timeOptions(1);
const courts = Array.from({ length: 10 }, (_, index) => `${index + 1}号场`);
const canSend = computed(() => !props.busy && !props.blocked && !props.locked && !props.sendBlocked
  && Boolean((props.followUp ? props.answer : props.message).trim()));

function insertField(text) {
  const current = props.followUp ? props.answer : props.message;
  if (current.includes(text)) return;
  const next = `${current.trimEnd()}${current.trim() ? '\n' : ''}${text}`;
  emit(props.followUp ? 'update:answer' : 'update:message', next);
}

function insertSelection(field, value) {
  if (!value) return;
  const current = props.followUp ? props.answer : props.message;
  const labels = { mode: '队列类型：', date: '日期：', windows2: '2小时时段：', courts2: '2小时场地：', windows1: '1小时时段：', courts1: '1小时场地：' };
  const append = ['windows2', 'courts2', 'windows1', 'courts1'].includes(field);
  const lines = current.split('\n');
  const lineIndex = lines.findIndex((line) => line.startsWith(labels[field]));
  if (lineIndex >= 0) {
    const existing = lines[lineIndex].slice(labels[field].length);
    const values = existing ? existing.split(/[、,，]/).map((item) => item.trim()) : [];
    if (!values.includes(value)) lines[lineIndex] = `${labels[field]}${append && existing ? `${existing}、` : ''}${value}`;
  } else {
    lines.push(`${labels[field]}${value}`);
  }
  emit(props.followUp ? 'update:answer' : 'update:message', lines.filter((line) => line.trim()).join('\n'));
}

function onSelect(field, event) {
  insertSelection(field, event.target.value);
  event.target.value = '';
}

function submit() {
  if (canSend.value) emit('send', props.followUp);
}
</script>

<template>
  <section class="proposal-composer" :class="{ 'is-suppressed': suppressed }" aria-label="预约需求输入">
    <form class="proposal-compose-form" @submit.prevent="submit">
      <label v-if="mode === 'edit'" class="proposal-target-select" for="proposal-target-plan">
        修改已有计划
        <select id="proposal-target-plan" :value="targetId" :disabled="selectionDisabled || busy" @change="emit('update:target-id', $event.target.value)">
          <option value="">选择要修改的计划</option>
          <option v-for="plan in plans" :key="plan.plan_id" :value="plan.plan_id">{{ plan.intent.venue_preference }} · {{ plan.intent.target_date }} · v{{ plan.version }}</option>
        </select>
      </label>
      <label class="sr-only" :for="followUp ? 'proposal-follow-up-answer' : 'proposal-first-message'">{{ followUp ? '补充回答' : mode === 'edit' ? '修改需求' : '预约需求' }}</label>
      <div class="proposal-input-box">
        <textarea
          v-if="followUp"
          id="proposal-follow-up-answer"
          :value="answer"
          data-testid="proposal-answer"
          aria-label="补充回答"
          rows="2"
          maxlength="4000"
          :disabled="busy || locked || blocked"
          :placeholder="status === 'ready' ? '继续修改或提问，例如“把场地换成4号场”' : mode === 'edit' ? '回答上方的问题就行，例如“4号场”' : '回答上方的问题就行，例如“14-16”或“1号和4号”'"
          @input="emit('update:answer', $event.target.value)"
          @keydown.enter.exact.prevent="submit"
          @keydown.ctrl.enter.prevent="submit"
          @keydown.meta.enter.prevent="submit"
        />
        <textarea
          v-else
          id="proposal-first-message"
          :value="message"
          data-testid="proposal-message"
          aria-label="预约需求"
          rows="2"
          maxlength="4000"
          :disabled="busy || locked || blocked"
          :placeholder="mode === 'edit' ? '例如：把优先场地改成4号场，时间保持不变' : '例如：后天 14-16 和 18-20，1号和4号场'"
          @input="emit('update:message', $event.target.value)"
          @keydown.enter.exact.prevent="submit"
          @keydown.ctrl.enter.prevent="submit"
          @keydown.meta.enter.prevent="submit"
        />
        <button
          class="primary-button proposal-send-button"
          :data-testid="followUp ? 'continue-proposal' : 'generate-proposal'"
          type="submit"
          :disabled="!canSend"
          :aria-label="busy ? '正在整理' : followUp ? '发送回答并继续' : mode === 'edit' ? '发送计划修改需求' : '发送预约需求'"
          @click.prevent="submit"
        >
          <span>{{ busy ? '处理中…' : '发送' }}</span>
        </button>
      </div>
      <button v-if="followUp" class="text-button" type="button" @click="emit('edit-request')">修改原描述</button>
      <div class="proposal-compose-meta">
        <details class="proposal-field-shortcuts">
          <summary><AppIcon name="plus" />补充字段</summary>
          <div v-if="mode === 'queue'" class="proposal-field-options" aria-label="选择预约字段并填入聊天框">
            <label>日期<input data-testid="proposal-field-date" type="date" :min="businessDate || undefined" :disabled="busy || locked || blocked" @change="onSelect('date', $event)"></label>
            <label>队列类型<select data-testid="proposal-field-mode" value="" :disabled="busy || locked || blocked" @change="onSelect('mode', $event)">
              <option value="">选择队列类型</option><option value="只要2小时">只抢2小时</option><option value="只要1小时">只抢1小时</option><option value="两种都要">1小时和2小时都抢</option>
            </select></label>
            <label>2小时时段<select data-testid="proposal-field-windows-2h" value="" :disabled="busy || locked || blocked" @change="onSelect('windows2', $event)">
              <option value="">选择时间段</option><option v-for="time in windows2" :key="time" :value="time">{{ time }}</option>
            </select></label>
            <label>2小时场地<select data-testid="proposal-field-courts-2h" value="" :disabled="busy || locked || blocked" @change="onSelect('courts2', $event)">
              <option value="">选择场地</option><option v-for="court in courts" :key="court" :value="court">{{ court }}</option>
            </select></label>
            <label>1小时时段<select data-testid="proposal-field-windows-1h" value="" :disabled="busy || locked || blocked" @change="onSelect('windows1', $event)">
              <option value="">选择时间段</option><option v-for="time in windows1" :key="time" :value="time">{{ time }}</option>
            </select></label>
            <label>1小时场地<select data-testid="proposal-field-courts-1h" value="" :disabled="busy || locked || blocked" @change="onSelect('courts1', $event)">
              <option value="">选择场地</option><option v-for="court in courts" :key="court" :value="court">{{ court }}</option>
            </select></label>
          </div>
          <div v-else class="proposal-field-options edit-field-options" aria-label="插入修改字段">
            <button v-for="field in fields" :key="field.key" :data-testid="`proposal-field-${field.key}`" type="button" :disabled="busy || locked || blocked" @click="insertField(field.text)">{{ field.label }}</button>
          </div>
        </details>
        <p v-if="blocked" class="composer-hint is-blocked">先完成预约凭据验证和支付密码设置，再发送需求。</p>
        <details v-else class="proposal-input-help"><summary>输入说明</summary><p class="composer-hint">{{ mode === 'edit' ? '只描述需要修改的内容；其他字段会保留 · Enter 发送，Shift+Enter 换行' : '先选队列类型，再确认日期；2小时和1小时的时段、场地分开核对 · Enter 发送，Shift+Enter 换行' }}</p></details>
      </div>
    </form>
  </section>
</template>

<style scoped>
.proposal-composer { min-width: 0; padding:8px 16px 16px; border-top: 1px solid var(--line); background: var(--surface); }
.proposal-composer.is-suppressed { display: none; }
.proposal-compose-form { display: grid; gap:8px; }
.proposal-target-select { display:grid; gap:8px; color:var(--muted); font-size:13px; }
.proposal-target-select select { min-height:var(--control-height); width:100%; padding:8px 12px; border:1px solid var(--line); border-radius:12px; background:var(--surface); color:var(--ink); font:inherit; }
.proposal-input-box { display: flex; align-items: flex-end; gap:8px; padding:8px 8px 8px 16px; border: 1px solid var(--line); border-radius:16px; background: var(--page); }
.proposal-input-box:focus-within { border-color: var(--brand); box-shadow: var(--focus); }
.proposal-input-box textarea { flex: 1; width: 100%; min-width: 0; min-height:var(--control-height); max-height: 120px; resize: vertical; border: 0; padding:8px 0; background: transparent; color: var(--ink); font: inherit; font-size: 15px; line-height: 1.55; }
.proposal-input-box textarea:focus-visible { outline: none; }
.proposal-input-box textarea:disabled { color: var(--muted); cursor: not-allowed; }
.proposal-input-box textarea::placeholder { color: var(--muted); opacity: 1; }
.proposal-send-button { flex: none; min-width: 72px; min-height:var(--control-height); padding:8px 16px; }
.proposal-compose-meta { display:flex; align-items:flex-start; flex-wrap:wrap; gap:4px 12px; }
.proposal-input-help { min-width:0; }
.proposal-input-help > summary { display:flex; align-items:center; min-height:44px; color:var(--muted); font-size:13px; cursor:pointer; }
.proposal-input-help[open], .proposal-field-shortcuts[open], .composer-hint.is-blocked { flex-basis:100%; }
.composer-hint { margin:0; color: var(--muted); font-size: 13px; line-height: 1.45; }
.composer-hint.is-blocked { color: var(--warning); font-weight: 600; }
.proposal-field-shortcuts { min-width:0; }
.proposal-field-shortcuts > summary { min-height:var(--control-height); display: flex; align-items: center; gap:8px; padding:0 8px; border-radius:8px; color: var(--brand); cursor: pointer; font-size: 13px; font-weight: 600; list-style: none; }
.proposal-field-shortcuts > summary::-webkit-details-marker { display: none; }
.proposal-field-shortcuts > summary :deep(.app-icon) { width: 16px; height: 16px; }
.proposal-field-shortcuts[open] > summary { background: var(--brand-soft); }
.proposal-field-options { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:8px; width:100%; max-width:720px; padding:12px; border:1px solid var(--line); border-radius:14px; background:var(--page); }
.proposal-field-options label { display:grid; gap:4px; min-width:0; color:var(--muted); font-size:12px; }
.proposal-field-options input, .proposal-field-options select { min-width:0; min-height:44px; padding:6px 10px; border:1px solid var(--line); border-radius:10px; background:var(--surface); color:var(--ink); font:inherit; font-size:13px; }
.edit-field-options { display:flex; flex-wrap:wrap; }
.edit-field-options button { min-height:var(--control-height); padding:8px 12px; border:1px solid var(--line); border-radius:999px; background:var(--surface); color:var(--ink); font-size:13px; cursor:pointer; }
.proposal-field-options button:hover:not(:disabled) { border-color: var(--brand); background: var(--brand-soft); }
.proposal-field-options button:disabled { opacity: .55; cursor: not-allowed; }
.proposal-composer :deep(button:focus-visible), .proposal-composer :deep(summary:focus-visible) { outline: 3px solid var(--brand); outline-offset: 2px; }
@media (max-width: 600px) {
  .proposal-composer { padding:8px; }
  .proposal-compose-meta { gap:4px 12px; }
  .proposal-input-box textarea { font-size: 16px; }
  .proposal-field-options { grid-template-columns:1fr; }
}
</style>
