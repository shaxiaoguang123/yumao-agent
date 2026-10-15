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
  locked: Boolean,
  selectionDisabled: Boolean,
});
const emit = defineEmits(['update:message', 'update:answer', 'update:targetId', 'send']);

const fields = [
  { key: 'date', label: '预约日期', text: '预约日期：' },
  { key: 'time', label: '开始时间', text: '开始时间：' },
  { key: 'duration', label: '预约时长', text: '预约时长：' },
  { key: 'venue', label: '场馆', text: '场馆：' },
  { key: 'courts', label: '场地顺序', text: '场地偏好顺序：' },
];
const canSend = computed(() => !props.busy && !props.blocked && !props.locked
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
  <section class="proposal-composer" aria-label="预约需求输入">
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
          placeholder="例如：10月24日18:00开始，打120分钟，东区体育馆，优先6号场，其次5号场。"
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
.proposal-composer{min-width:0;padding:12px 18px 14px;border-top:1px solid var(--line);background:var(--surface)}
.proposal-target-field{display:grid;gap:4px;margin:0 0 8px;font-size:12px;font-weight:650}.proposal-target-field select{width:100%;min-height:42px;padding:8px 12px;border:1px solid var(--line);border-radius:9px;background:var(--surface);color:var(--ink);font:inherit;font-size:13px}.proposal-target-field small{color:var(--muted);font-weight:400}
.proposal-compose-form{display:grid;gap:6px}.proposal-input-box{display:flex;align-items:flex-end;gap:10px;padding:9px 10px 9px 14px;border:1px solid var(--line);border-radius:14px;background:#f7f9f7;transition:border-color 120ms ease,box-shadow 120ms ease}.proposal-input-box:focus-within{border-color:var(--brand);outline:3px solid var(--brand);outline-offset:2px;box-shadow:0 0 0 2px var(--brand-soft)}
.proposal-input-box textarea{flex:1;width:100%;min-width:0;min-height:58px;max-height:160px;resize:vertical;border:0;padding:7px 0;background:transparent;color:var(--ink);font:inherit;font-size:14px;line-height:1.55}.proposal-input-box textarea:focus-visible{outline:none}.proposal-input-box textarea:disabled{color:var(--muted);cursor:not-allowed}.proposal-input-box textarea::placeholder{color:#74847c;opacity:1}
.proposal-send-button{flex:none;min-width:64px;min-height:44px;padding:8px 14px}.proposal-compose-meta{display:flex;align-items:center;justify-content:space-between;gap:10px;min-height:28px}.composer-hint{margin:0;color:var(--muted);font-size:11px;line-height:1.4;text-align:right}.composer-hint.is-blocked{color:var(--warning);font-weight:600}
.proposal-field-shortcuts{position:relative;flex:none}.proposal-field-shortcuts>summary{min-height:44px;display:flex;align-items:center;gap:5px;padding:0 8px;border-radius:7px;color:var(--muted);cursor:pointer;font-size:12px;list-style:none}.proposal-field-shortcuts>summary::-webkit-details-marker{display:none}.proposal-field-shortcuts>summary :deep(.app-icon){width:16px;height:16px;color:var(--brand-dark)}.proposal-field-shortcuts[open]>summary{background:var(--brand-soft);color:var(--brand-dark)}.proposal-field-options{position:absolute;bottom:calc(100% + 4px);left:0;z-index:3;display:flex;flex-wrap:wrap;gap:6px;width:min(360px,calc(100vw - 60px));padding:10px;border:1px solid var(--line);border-radius:10px;background:var(--surface);box-shadow:0 8px 22px rgb(20 40 30 / 12%)}.proposal-field-options button{min-height:44px;padding:6px 10px;border:1px solid var(--line);border-radius:999px;background:var(--surface);color:var(--brand-dark);font-size:12px;cursor:pointer}.proposal-field-options button:hover:not(:disabled){background:var(--brand-soft);border-color:var(--brand)}.proposal-field-options button:disabled{opacity:.55;cursor:not-allowed}
.proposal-composer :deep(button:focus-visible),.proposal-composer :deep(select:focus-visible),.proposal-composer :deep(summary:focus-visible){outline:3px solid var(--brand);outline-offset:2px}
@media(max-width:600px){.proposal-composer{padding:10px 12px 12px}.proposal-target-field select{font-size:16px}.proposal-input-box{gap:6px;padding:8px}.proposal-input-box textarea{font-size:16px}.proposal-send-button{min-width:54px;padding:7px 10px}.proposal-compose-meta{align-items:flex-start}.composer-hint{max-width:72%;font-size:10px}.proposal-field-shortcuts>summary{padding:0 4px}}
</style>
