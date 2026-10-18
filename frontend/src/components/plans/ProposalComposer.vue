<script setup>
import { computed } from 'vue';
import AppIcon from '../AppIcon.vue';

const props = defineProps({
  message: { type: String, default: '' },
  answer: { type: String, default: '' },
  mode: { type: String, default: 'new' },
  targetId: { type: String, default: '' },
  plans: { type: Array, default: () => [] },
  status: { type: String, default: 'idle' },
  followUp: Boolean,
  busy: Boolean,
  blocked: Boolean,
  sendBlocked: Boolean,
  suppressed: Boolean,
  locked: Boolean,
  selectionDisabled: Boolean,
});
const emit = defineEmits(['update:message', 'update:answer', 'update:targetId', 'send', 'edit-request']);

const fields = [
  { key: 'date', label: '预约日期', text: '预约日期：' },
  { key: 'time', label: '开始时间', text: '开始时间：' },
  { key: 'duration', label: '预约时长', text: '预约时长：' },
  { key: 'venue', label: '场馆', text: '场馆：' },
  { key: 'courts', label: '场地顺序', text: '场地偏好顺序：' },
];
const canSend = computed(() => !props.busy && !props.blocked && !props.locked && !props.sendBlocked
  && (props.mode !== 'edit' || Boolean(props.targetId))
  && Boolean((props.followUp ? props.answer : props.message).trim()));

function insertField(text) {
  const current = props.followUp ? props.answer : props.message;
  if (current.includes(text)) return;
  const next = `${current.trimEnd()}${current.trim() ? '\n' : ''}${text}`;
  emit(props.followUp ? 'update:answer' : 'update:message', next);
}

function submit() {
  if (canSend.value) emit('send', props.followUp);
}
</script>

<template>
  <section class="proposal-composer" :class="{ 'is-suppressed': suppressed }" aria-label="预约需求输入">
    <label v-if="mode === 'edit'" class="proposal-target-field" for="proposal-target">
      <span class="sr-only">要修改的计划</span>
      <select
        id="proposal-target"
        :value="targetId"
        data-testid="proposal-target"
        :disabled="busy || locked || selectionDisabled"
        @change="emit('update:targetId', $event.target.value)"
      >
        <option value="">请选择已有计划</option>
        <option v-for="plan in plans" :key="plan.plan_id" :value="plan.plan_id">{{ plan.intent.venue_preference }} · {{ plan.intent.target_date }} · v{{ plan.version }}</option>
      </select>
      <small v-if="!plans.length">当前凭据下没有可修改的计划；可以重新开始新建意向。</small>
    </label>

    <form class="proposal-compose-form" @submit.prevent="submit">
      <label class="sr-only" :for="followUp ? 'proposal-follow-up-answer' : 'proposal-first-message'">{{ followUp ? '补充回答' : '预约需求' }}</label>
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
          placeholder="回答上方的问题；不确定的部分可以继续说明。"
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
          placeholder="例如：10月24日 18:00 开始，打 2 小时，东区体育馆，6 号场优先"
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
          :aria-label="busy ? '正在整理' : followUp ? '发送回答并继续' : '发送预约需求'"
          @click.prevent="submit"
        >
          <span>{{ busy ? '处理中…' : '发送' }}</span>
        </button>
      </div>
      <button v-if="followUp" class="text-button" type="button" @click="emit('edit-request')">修改原描述</button>
      <div class="proposal-compose-meta">
        <details class="proposal-field-shortcuts">
          <summary><AppIcon name="plus" />补充字段</summary>
          <div class="proposal-field-options" aria-label="插入预约字段">
            <button v-for="field in fields" :key="field.key" :data-testid="`proposal-field-${field.key}`" type="button" :disabled="busy || locked || blocked" @click="insertField(field.text)">{{ field.label }}</button>
          </div>
        </details>
        <p v-if="blocked" class="composer-hint is-blocked">先完成预约凭据验证和支付密码设置，再发送需求。</p>
        <p v-else-if="mode === 'edit' && !targetId" class="composer-hint">先选择要修改的计划。</p>
        <p v-else class="composer-hint">日期、时间、时长、场馆和场地偏好需要明确 · Enter 发送，Shift+Enter 换行</p>
      </div>
    </form>
  </section>
</template>

<style scoped>
.proposal-composer { min-width: 0; padding:8px 16px 16px; border-top: 1px solid var(--line); background: var(--surface); }
.proposal-composer.is-suppressed { display: none; }
.proposal-target-field { display: grid; gap:8px; margin:0 0 8px; font-size: 13px; font-weight: 600; }
.proposal-target-field select { width: 100%; min-height:var(--control-height); padding:8px 8px; border: 1px solid var(--line); border-radius:16px; background: var(--surface); color: var(--ink); font: inherit; font-size: 15px; font-weight: 400; }
.proposal-target-field small { color: var(--muted); font-weight: 400; }
.proposal-compose-form { display: grid; gap:8px; }
.proposal-input-box { display: flex; align-items: flex-end; gap:8px; padding:8px 8px 8px 16px; border: 1px solid var(--line); border-radius:16px; background: var(--page); }
.proposal-input-box:focus-within { border-color: var(--brand); box-shadow: var(--focus); }
.proposal-input-box textarea { flex: 1; width: 100%; min-width: 0; min-height:var(--control-height); max-height: 120px; resize: vertical; border: 0; padding:8px 0; background: transparent; color: var(--ink); font: inherit; font-size: 15px; line-height: 1.55; }
.proposal-input-box textarea:focus-visible { outline: none; }
.proposal-input-box textarea:disabled { color: var(--muted); cursor: not-allowed; }
.proposal-input-box textarea::placeholder { color: var(--muted); opacity: 1; }
.proposal-send-button { flex: none; min-width: 72px; min-height:var(--control-height); padding:8px 16px; }
.proposal-compose-meta { display: flex; align-items: center; justify-content: space-between; gap:8px; }
.composer-hint { margin:0; color: var(--muted); font-size: 13px; line-height: 1.45; }
.composer-hint.is-blocked { color: var(--warning); font-weight: 600; }
.proposal-field-shortcuts { position: relative; flex: none; }
.proposal-field-shortcuts > summary { min-height:var(--control-height); display: flex; align-items: center; gap:8px; padding:0 8px; border-radius:8px; color: var(--brand); cursor: pointer; font-size: 13px; font-weight: 600; list-style: none; }
.proposal-field-shortcuts > summary::-webkit-details-marker { display: none; }
.proposal-field-shortcuts > summary :deep(.app-icon) { width: 16px; height: 16px; }
.proposal-field-shortcuts[open] > summary { background: var(--brand-soft); }
.proposal-field-options { position: absolute; bottom: calc(100% + 6px); left: 0; z-index: 3; display: flex; flex-wrap: wrap; gap:8px; width: min(360px, calc(100vw - 48px)); padding:8px; border: 1px solid var(--line); border-radius:16px; background: var(--surface); box-shadow: var(--shadow); }
.proposal-field-options button { min-height:var(--control-height); padding:8px 8px; border: 1px solid var(--line); border-radius:16px; background: var(--surface); color: var(--ink); font-size: 13px; cursor: pointer; }
.proposal-field-options button:hover:not(:disabled) { border-color: var(--brand); background: var(--brand-soft); }
.proposal-field-options button:disabled { opacity: .55; cursor: not-allowed; }
.proposal-composer :deep(button:focus-visible), .proposal-composer :deep(select:focus-visible), .proposal-composer :deep(summary:focus-visible) { outline: 3px solid var(--brand); outline-offset: 2px; }
@media (max-width: 600px) {
  .proposal-composer { padding:8px; }
  .proposal-compose-meta { align-items: flex-start; flex-direction: column; }
  .proposal-input-box textarea, .proposal-target-field select { font-size: 16px; }
}
</style>
