<script setup>
import { computed, nextTick, ref, watch } from 'vue';
import { RouterLink } from 'vue-router';
import AppIcon from '../AppIcon.vue';

const props = defineProps({
  message: { type: String, default: '' },
  answers: { type: Array, default: () => [] },
  questionHistory: { type: Array, default: () => [] },
  questions: { type: Array, default: () => [] },
  pendingTurn: { type: String, default: '' },
  status: { type: String, default: 'idle' },
  error: { type: String, default: '' },
  savedNotice: { type: String, default: '' },
  trace: { type: Array, default: () => [] },
  showCredentialStatus: Boolean,
  slots: { type: Array, default: () => [] },
});
const emit = defineEmits(['restart']);

function slotHeading(questions) {
  const text = (questions || []).join(' ');
  if (/场馆|哪家/.test(text)) return '场馆';
  if (/场地|号场/.test(text)) return '场地';
  if (/多久|时长|小时|分钟/.test(text)) return '时长';
  if (/几点|开始时间|什么时间/.test(text)) return '时间';
  if (/日期|几月|哪一天|哪天|几号/.test(text)) return '日期';
  return '还缺一项';
}

const feed = ref(null);
const transcript = computed(() => {
  const items = [];
  const conversationStarted = props.status !== 'idle' || props.answers.length > 0
    || props.questionHistory.length > 0 || props.questions.length > 0
    || Boolean(props.error || props.savedNotice);
  if (!props.message.trim() || !conversationStarted) {
    items.push({ id: 'welcome', role: 'assistant', kind: 'welcome' });
    return items;
  }
  items.push({ id: 'initial-request', role: 'user', kind: 'text', text: props.message });
  props.questionHistory.forEach((round, index) => {
    items.push({ id: `questions-${index}`, role: 'assistant', kind: 'questions', questions: round });
    if (props.answers[index]) {
      items.push({ id: `answer-${index}`, role: 'user', kind: 'text', text: props.answers[index] });
    }
  });
  if (props.questions.length && props.status !== 'unsupported') {
    items.push({ id: 'current-questions', role: 'assistant', kind: 'questions', questions: props.questions });
  }
  if (props.pendingTurn && props.status === 'generating') {
    items.push({ id: 'pending-answer', role: 'user', kind: 'text', text: props.pendingTurn, pending: true });
  }
  if (props.status === 'generating') items.push({ id: 'thinking', role: 'assistant', kind: 'thinking' });
  if (props.status === 'ready') items.push({ id: 'draft-ready', role: 'assistant', kind: 'ready' });
  if (props.status === 'unsupported') items.push({ id: 'unsupported', role: 'assistant', kind: 'unsupported', questions: props.questions });
  if (props.error) items.push({ id: 'request-error', role: 'assistant', kind: 'error', text: props.error });
  if (props.savedNotice) items.push({ id: 'saved', role: 'assistant', kind: 'saved', text: props.savedNotice });
  return items;
});

watch(
  () => [props.message, props.answers.length, props.questionHistory.length, props.questions.length, props.status, props.error, props.savedNotice, props.trace.length],
  async () => {
    await nextTick();
    if (feed.value) feed.value.scrollTop = feed.value.scrollHeight;
  },
  { flush: 'post' },
);
</script>

<template>
  <section class="proposal-chat" aria-labelledby="proposal-chat-title">
    <header class="proposal-chat-heading">
      <div class="proposal-chat-identity">
        <span class="proposal-chat-avatar"><AppIcon name="bot" /></span>
        <div><h2 id="proposal-chat-title">预约助手</h2><p>先选新建或修改，再写下已经确定的安排。</p></div>
      </div>
      <div class="chat-header-actions">
        <slot name="header-actions" />
        <RouterLink class="proposal-settings" :to="{ name: 'ai-models' }" aria-label="模型设置" title="模型设置"><AppIcon name="settings" /></RouterLink>
        <button class="chat-restart-button" data-testid="restart-conversation" type="button" aria-label="重新开始对话" title="重新开始对话" @click="emit('restart')"><slot name="restart-icon"><AppIcon name="refresh" /></slot></button>
      </div>
    </header>
    <div v-if="showCredentialStatus && $slots['system-message']" class="chat-status-bar"><slot name="system-message" /></div>
    <ol v-if="slots.length" class="slot-strip" aria-label="预约信息进度">
      <li v-for="slot in slots" :key="slot.id" :class="`is-${slot.state}`">
        <span>{{ slot.label }}</span>
        <strong>{{ slot.display || (slot.state === 'current' ? '正在确认' : '未填写') }}</strong>
      </li>
    </ol>

    <div ref="feed" class="proposal-chat-messages" role="log" aria-live="polite" aria-relevant="additions text">
      <div class="chat-conversation-group">
       <ol class="chat-message-list">
        <li v-for="item in transcript" :key="item.id" class="chat-row" :class="[`is-${item.role}`, { 'is-welcome': item.kind === 'welcome' }]">
          <div class="chat-bubble" :class="`bubble-${item.kind}`">
            <template v-if="item.kind === 'welcome'">
              <strong>先选择要做的事</strong>
              <p>新建是从一句话开始。修改是在已有计划上调整。缺的部分我会一次问一项。</p>
              <slot name="welcome-actions" />
            </template>
            <template v-else-if="item.kind === 'questions'">
              <strong>{{ slotHeading(item.questions) }}</strong>
              <p v-for="(question, index) in item.questions" :key="`${index}-${question}`">{{ question }}</p>
            </template>
            <template v-else-if="item.kind === 'thinking'">
              <span class="chat-thinking-dot" aria-hidden="true"></span>正在整理并核对预约信息…
            </template>
            <template v-else-if="item.kind === 'ready'">
              <strong>草案已生成</strong>
              <p>请在下方审核卡核对字段后再保存。</p>
            </template>
            <template v-else-if="item.kind === 'error'">
              <p role="alert">{{ item.text }} <RouterLink v-if="item.text.includes('尚未配置') || item.text.includes('模型设置') || item.text.includes('密钥')" :to="{ name: 'ai-models' }">前往设置AI模型</RouterLink></p>
            </template>
            <template v-else-if="item.kind === 'unsupported'">
              <strong>这项请求暂不支持</strong>
              <p>助手只整理预约意向，不执行预约、查询、付款或创建任务。</p>
              <ul v-if="item.questions?.length"><li v-for="(question, index) in item.questions" :key="`${index}-${question}`">{{ question }}</li></ul>
            </template>
            <template v-else>{{ item.text }}</template>
            <small v-if="item.pending" class="chat-pending-label">发送中</small>
          </div>
        </li>
        <slot name="conversation-extra" />
       </ol>
      </div>
    </div>

    <details v-if="trace.length" class="proposal-trace">
      <summary><span>本次操作轨迹</span><span>{{ trace.length }} 条</span></summary>
      <p class="proposal-trace-note">记录提交、校验和保存状态，不包含模型隐藏推理。</p>
      <ol v-if="trace.length" class="proposal-trace-list">
        <li v-for="(item, index) in trace" :key="item.id" class="trace-item">
          <span class="trace-index">{{ index + 1 }}</span>
          <div><strong>{{ item.title }}</strong><p>{{ item.detail }}</p></div>
          <time>{{ item.time }}</time>
        </li>
      </ol>
      <p v-else class="muted">发送预约需求后会显示处理步骤。</p>
    </details>

    <slot name="composer" />
  </section>
</template>

<style scoped>
.proposal-chat { display: flex; flex-direction: column; width: 100%; height: auto; min-height:0; overflow: hidden; border: 1px solid var(--line); border-radius:8px; background: var(--surface); }
.slot-strip { display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)); gap:8px; margin:0; padding:8px 16px; list-style: none; border-bottom: 1px solid var(--line); background: var(--surface); }
.slot-strip li { min-width: 0; padding:8px; border-radius:8px; background: var(--page); }
.slot-strip span, .slot-strip strong { display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.slot-strip span { color: var(--muted); font-size: 12px; }
.slot-strip strong { margin-top:8px; font-size: 13px; font-weight: 600; }
.slot-strip .is-current { background: var(--brand-soft); }
.slot-strip .is-current strong { color: var(--brand); }
.slot-strip .is-done strong { color: var(--ink); }
.slot-strip .is-empty strong, .slot-strip .is-draft strong { color: var(--muted); font-weight: 500; }
.proposal-chat-heading { display: flex; justify-content: space-between; align-items: center; gap:16px; min-height:0; padding:8px 16px; border-bottom: 1px solid var(--line); }
.proposal-chat-identity { display: flex; align-items: center; gap:8px; min-width: 0; }
.proposal-chat-avatar { flex: none; width: 36px; height: 36px; display: grid; place-items: center; border-radius:8px; background: var(--brand-soft); color: var(--brand); }
.proposal-chat-avatar :deep(.app-icon) { width: 20px; height: 20px; }
.proposal-chat-heading h2 { margin:0; font-size: 17px; font-weight: 600; }
.proposal-chat-heading p { margin:8px 0 0; color: var(--muted); font-size: 13px; line-height: 1.4; }
.chat-header-actions { display: flex; align-items: center; justify-content: flex-end; flex-wrap: wrap; gap:8px; min-width: 0; }
.proposal-settings, .chat-restart-button { flex: none; width: 44px; height: 44px; display: grid; place-items: center; border: 1px solid var(--line); border-radius:16px; background: var(--surface); color: var(--muted); }
.proposal-settings:hover, .chat-restart-button:hover { border-color: var(--brand); background: var(--brand-soft); color: var(--brand); }
.chat-restart-button { cursor: pointer; }
.chat-status-bar { padding:0 16px; border-bottom: 1px solid var(--line); background: var(--page); }
.proposal-chat-messages { display: flex; flex: 0 1 auto; min-height:0; max-height: 360px; overflow-y: auto; overscroll-behavior: contain; padding:16px; background: var(--page); }
.chat-conversation-group { width: 100%; max-width: 760px; margin:0 auto; }
.chat-message-list { display: grid; gap:8px; padding:0; margin:0; list-style: none; }
.chat-row { display: flex; min-width: 0; }
.chat-row.is-user { justify-content: flex-end; }
.chat-row.is-welcome { display: block; }
.chat-bubble { max-width: min(88%, 640px); padding:8px 16px; border-radius:16px; background: var(--surface); color: var(--ink); white-space: pre-wrap; overflow-wrap: anywhere; font-size: 15px; line-height: 1.55; }
.is-user .chat-bubble { background: var(--brand-soft); }
.bubble-welcome { max-width: none; padding:8px 0 0; background: transparent; }
.chat-bubble strong { display: block; font-size: 17px; font-weight: 600; }
.chat-bubble p { margin:8px 0 0; color: var(--muted); font-size: 15px; }
.chat-example { padding:8px 8px; border-radius:8px; background: var(--surface); color: var(--ink) !important; font-size: 13px !important; line-height: 1.55; }
.chat-bubble p[role=alert] { color: var(--danger); }
.chat-bubble p[role=alert] a { display: inline-flex; margin-left:8px; font-weight: 600; }
.chat-bubble ul { margin:8px 0 0; padding-left:16px; }
.bubble-thinking { color: var(--muted); background: transparent; }
.bubble-error { background: var(--danger-soft); color: var(--danger); }
.bubble-error p { color: inherit; }
.bubble-saved, .bubble-ready { background: var(--success-soft); }
.bubble-artifact { width: min(100%, 720px); max-width: 100%; padding:0; background: transparent; }
.bubble-artifact > section { margin:0 !important; }
.chat-pending-label { display: block; margin-top:8px; color: var(--muted); font-size: 13px; }
.chat-thinking-dot { display: inline-block; width: 8px; height: 8px; margin-right:8px; border-radius:50%; background: var(--brand); animation: chat-pulse 1.2s ease-in-out infinite; }
.proposal-trace { border-top: 1px solid var(--line); padding:0 16px; background: var(--surface); }
.proposal-trace summary { display: flex; justify-content: space-between; align-items: center; min-height:var(--control-height); cursor: pointer; font-size: 13px; font-weight: 600; list-style-position: inside; }
.proposal-trace summary span + span { color: var(--muted); font-weight: 500; }
.proposal-trace-note, .proposal-trace > .muted { margin:0 0 8px; color: var(--muted); font-size: 13px; }
.proposal-trace-list { display: grid; gap:8px; padding:0 0 8px; margin:0; list-style: none; }
.trace-item { display: grid; grid-template-columns: 24px minmax(0, 1fr) auto; gap:8px; align-items: start; }
.trace-index { width: 22px; height: 22px; display: grid; place-items: center; border-radius:50%; background: var(--brand-soft); color: var(--brand); font-size: 12px; font-weight: 600; }
.trace-item strong { font-size: 13px; }
.trace-item p, .trace-item time { margin:8px 0 0; color: var(--muted); font-size: 13px; }
.trace-item time { white-space: nowrap; }
@keyframes chat-pulse { 50% { opacity: .35; } }
@media (max-width: 680px) {
  .slot-strip { grid-template-columns: repeat(3, minmax(0, 1fr)); }
  .proposal-chat { height: auto; min-height:0; }
  .proposal-chat-heading { align-items: flex-start; }
  .chat-header-actions :deep(.plan-credential-control) { max-width: 100%; }
  .proposal-chat-messages { min-height:0; max-height: 48vh; }
  .chat-bubble { max-width: 100%; }
  .trace-item { grid-template-columns: 22px minmax(0, 1fr); }
  .trace-item time { grid-column: 2; }
}
@media (max-width: 420px) {
  .proposal-chat-heading { flex-wrap: wrap; }
  .chat-header-actions { width: 100%; justify-content: flex-end; }
}
@media (prefers-reduced-motion: reduce) { .chat-thinking-dot { animation: none; } }
</style>
