<script setup>
import { computed, nextTick, ref, watch } from 'vue';
import { RouterLink } from 'vue-router';
import AppIcon from '../AppIcon.vue';

const props = defineProps({
  message: { type: String, default: '' },
  answers: { type: Array, default: () => [] },
  questionHistory: { type: Array, default: () => [] },
  replyHistory: { type: Array, default: () => [] },
  roundHeadings: { type: Array, default: () => [] },
  heading: { type: String, default: '' },
  assistantSubtitle: { type: String, default: '说出想订的日期和时间，我帮你排好抢票队列。' },
  welcomeTitle: { type: String, default: '说说想订哪天、什么时间' },
  welcomeDescription: { type: String, default: '一句话就行，缺的我会一次问一项。例如：' },
  welcomeExample: { type: String, default: '后天 14-16 和 18-20，1号和4号场' },
  welcomeFooter: { type: String, default: '先排 2 小时的队列，再问要不要 1 小时的备选。' },
  questions: { type: Array, default: () => [] },
  pendingTurn: { type: String, default: '' },
  status: { type: String, default: 'idle' },
  error: { type: String, default: '' },
  savedNotice: { type: String, default: '' },
  trace: { type: Array, default: () => [] },
  showCredentialStatus: Boolean,
  showConversationHistory: Boolean,
  conversations: { type: Array, default: () => [] },
  activeConversationId: { type: String, default: '' },
  asking: { type: String, default: '' },
  contextualReply: { type: String, default: '' },
  modeChoices: { type: Array, default: () => [] },
  interactionDisabled: Boolean,
  slots: { type: Array, default: () => [] },
});
const emit = defineEmits(['restart', 'new-conversation', 'select-conversation', 'quick-reply']);

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
    items.push({ id: `questions-${index}`, role: 'assistant', kind: 'questions', heading: props.roundHeadings[index] || '',
      questions: round, contextualReply: props.replyHistory[index] || '' });
    if (props.answers[index]) {
      items.push({ id: `answer-${index}`, role: 'user', kind: 'text', text: props.answers[index] });
    }
  });
  if (props.questions.length && props.status !== 'unsupported') {
    items.push({ id: 'current-questions', role: 'assistant', kind: 'questions', heading: props.heading,
      questions: props.questions, contextualReply: props.contextualReply, choices: props.asking === 'booking_mode' ? props.modeChoices : [] });
  }
  if (!props.questions.length && props.contextualReply && ['ready', 'needs_input'].includes(props.status)) {
    items.push({ id: 'current-reply', role: 'assistant', kind: 'questions', questions: [], contextualReply: props.contextualReply });
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
  () => [props.message, props.answers.length, props.questionHistory.length, props.replyHistory.length,
    props.questions.length, props.contextualReply, props.activeConversationId, props.status, props.error, props.savedNotice, props.trace.length],
  async () => {
    await nextTick();
    if (feed.value) feed.value.scrollTop = feed.value.scrollHeight;
  },
  { flush: 'post' },
);

function selectConversation(id) {
  emit('select-conversation', id);
  const menu = feed.value?.closest('.proposal-chat')?.querySelector('.conversation-history');
  if (menu) menu.open = false;
}

function formatHistoryDate(value) {
  return Number.isSafeInteger(value) ? new Intl.DateTimeFormat('zh-CN', { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' }).format(new Date(value)) : '';
}
</script>

<template>
  <section class="proposal-chat" :class="{ 'has-queue-preview': Boolean($slots['queue-preview']) }" aria-labelledby="proposal-chat-title">
    <header class="proposal-chat-heading">
      <div class="proposal-chat-identity">
        <span class="proposal-chat-avatar"><AppIcon name="bot" /></span>
        <div class="chat-identity-title"><h2 id="proposal-chat-title">预约助手</h2><div v-if="showCredentialStatus && $slots['system-message']" class="chat-status-bar"><slot name="system-message" /></div></div>
      </div>
      <div class="chat-header-actions">
        <div v-if="$slots['header-actions']" class="chat-credential-toolbar"><slot name="header-actions" /></div>
        <div class="chat-conversation-actions">
        <RouterLink class="proposal-settings" :to="{ name: 'ai-models' }" aria-label="模型设置" title="模型设置"><AppIcon name="settings" /></RouterLink>
        <button v-if="showConversationHistory" class="chat-new-button" data-testid="restart-conversation" type="button" aria-label="新对话" :disabled="interactionDisabled" @click="emit('new-conversation')"><AppIcon name="plus" /><span class="chat-action-label">新对话</span></button>
        <button v-else class="chat-restart-button" data-testid="restart-conversation" type="button" aria-label="重新开始对话" title="重新开始对话" @click="emit('restart')"><slot name="restart-icon"><AppIcon name="refresh" /></slot></button>
        <details v-if="showConversationHistory" class="conversation-history">
          <summary :aria-label="`历史对话，${conversations.length}条`">历史 <span>{{ conversations.length }}</span></summary>
          <div class="conversation-history-menu" aria-label="历史对话列表">
            <p v-if="!conversations.length" class="conversation-history-empty">还没有历史对话。</p>
            <button v-for="item in conversations" :key="item.conversation_id" type="button" class="conversation-history-item"
              :class="{ 'is-current': item.conversation_id === activeConversationId }"
              :aria-current="item.conversation_id === activeConversationId ? 'true' : undefined"
              :disabled="interactionDisabled" @click="selectConversation(item.conversation_id)">
              <strong>{{ item.title }}</strong><small>{{ item.preview }}</small>
              <span><time>{{ formatHistoryDate(item.updated_at_utc_ms) }}</time><em>{{ item.status === 'active' ? '进行中' : '已保存' }}</em></span>
            </button>
          </div>
        </details>
        </div>
      </div>
    </header>
    <ol v-if="slots.length" class="slot-strip" aria-label="预约信息进度">
      <li v-for="slot in slots" :key="slot.id" :class="`is-${slot.state}`">
        <span>{{ slot.label }}</span>
        <strong>{{ slot.display || (slot.state === 'current' ? '正在确认' : '未填写') }}</strong>
      </li>
    </ol>

    <div class="proposal-chat-body">
      <div class="proposal-chat-main">
        <div ref="feed" class="proposal-chat-messages" role="log" aria-live="polite" aria-relevant="additions text">
          <div class="chat-conversation-group"><ol class="chat-message-list">
            <li v-for="item in transcript" :key="item.id" class="chat-row" :class="[`is-${item.role}`, { 'is-welcome': item.kind === 'welcome' }]">
              <div class="chat-bubble" :class="`bubble-${item.kind}`">
                <template v-if="item.kind === 'welcome'">
                  <strong>{{ welcomeTitle }}</strong>
                  <div v-if="modeChoices.length" class="mode-quick-choices" aria-label="选择预约队列类型">
                    <button v-for="choice in modeChoices" :key="choice.value" type="button" :disabled="interactionDisabled" @click="emit('quick-reply', choice.value)">
                      <strong>{{ choice.label }}</strong><small>{{ choice.description }}</small>
                    </button>
                  </div>
                  <details class="chat-welcome-help"><summary>示例与说明</summary><p>{{ welcomeDescription }}</p><p class="chat-example">{{ welcomeExample }}</p><p>{{ welcomeFooter }}</p></details>
                </template>
                <template v-else-if="item.kind === 'questions'">
                  <strong v-if="item.heading">{{ item.heading }}</strong>
                  <p v-if="item.contextualReply" class="contextual-reply">{{ item.contextualReply }}</p>
                  <p v-for="(question, index) in item.questions" :key="`${index}-${question}`">{{ question }}</p>
                  <div v-if="item.choices?.length" class="mode-quick-choices" aria-label="选择预约队列类型">
                    <button v-for="choice in item.choices" :key="choice.value" type="button" :disabled="interactionDisabled" @click="emit('quick-reply', choice.value)">
                      <strong>{{ choice.label }}</strong><small>{{ choice.description }}</small>
                    </button>
                  </div>
                </template>
                <template v-else-if="item.kind === 'thinking'"><span class="chat-thinking-dot" aria-hidden="true"></span>正在整理并核对预约信息…</template>
                <template v-else-if="item.kind === 'ready'"><strong>草案已生成</strong><p>请在下方审核卡核对字段后再保存。</p></template>
                <template v-else-if="item.kind === 'error'"><p role="alert">{{ item.text }} <RouterLink v-if="item.text.includes('尚未配置') || item.text.includes('模型设置') || item.text.includes('密钥')" :to="{ name: 'ai-models' }">前往设置AI模型</RouterLink></p></template>
                <template v-else-if="item.kind === 'unsupported'"><strong>这项请求暂不支持</strong><p>助手只整理预约意向，不执行预约、查询、付款或创建任务。</p><ul v-if="item.questions?.length"><li v-for="(question, index) in item.questions" :key="`${index}-${question}`">{{ question }}</li></ul></template>
                <template v-else>{{ item.text }}</template>
                <small v-if="item.pending" class="chat-pending-label">发送中</small>
              </div>
            </li>
            <slot name="conversation-extra" />
          </ol></div>
        </div>
        <details v-if="trace.length" class="proposal-trace">
          <summary><span>处理记录</span><span>{{ trace.length }} 步</span></summary>
          <p class="proposal-trace-note">记录校验和保存状态，不包含模型隐藏推理。</p>
          <ol class="proposal-trace-list"><li v-for="(item, index) in trace" :key="item.id" class="trace-item">
            <span class="trace-index">{{ index + 1 }}</span><div><strong>{{ item.title }}</strong><p>{{ item.detail }}</p></div><time>{{ item.time }}</time>
          </li></ol>
        </details>
        <slot name="composer" />
      </div>
      <div v-if="$slots['queue-preview']" class="proposal-chat-preview"><slot name="queue-preview" /></div>
    </div>
  </section>
</template>

<style scoped>
.proposal-chat { display:flex; flex-direction:column; width:100%; min-width:0; border:1px solid var(--line); border-radius:20px; background:var(--surface); }
.proposal-chat-heading { display:flex; justify-content:space-between; align-items:center; gap:16px; min-height:60px; padding:8px 16px; border-bottom:1px solid var(--line); }
.proposal-chat-identity { display:flex; align-items:center; gap:12px; min-width:0; }
.proposal-chat-avatar { flex:none; width:32px; height:32px; display:grid; place-items:center; border-radius:14px; background:var(--brand-soft); color:var(--brand); }
.proposal-chat-avatar :deep(.app-icon) { width:20px; height:20px; }
.proposal-chat-heading h2 { margin:0; font-size:17px; font-weight:650; }
.proposal-chat-heading p { margin:4px 0 0; color:var(--muted); font-size:13px; line-height:1.4; }
.chat-header-actions { display:flex; align-items:center; justify-content:flex-end; flex-wrap:wrap; gap:8px; min-width:0; }
.chat-credential-toolbar { min-width:0; }
.chat-conversation-actions { display:flex; align-items:center; gap:6px; }
.proposal-settings, .chat-restart-button, .chat-new-button, .conversation-history > summary { flex:none; min-height:44px; display:inline-flex; align-items:center; justify-content:center; gap:6px; padding:0 12px; border:1px solid var(--line); border-radius:999px; background:var(--surface); color:var(--muted); font:inherit; font-size:13px; text-decoration:none; }
.proposal-settings, .chat-restart-button { width:44px; padding:0; }
.chat-new-button { color:var(--brand); cursor:pointer; }
.chat-new-button :deep(.app-icon) { width:16px; height:16px; }
.proposal-settings:hover, .chat-restart-button:hover, .chat-new-button:hover:not(:disabled), .conversation-history > summary:hover { border-color:var(--brand); background:var(--brand-soft); color:var(--brand); }
.chat-restart-button { cursor:pointer; }
.chat-new-button:disabled { opacity:.55; cursor:not-allowed; }
.conversation-history { position:relative; flex:none; }
.conversation-history > summary { cursor:pointer; list-style:none; }
.conversation-history > summary::-webkit-details-marker { display:none; }
.conversation-history > summary span { color:var(--brand); font-weight:700; }
.conversation-history-menu { position:absolute; top:calc(100% + 8px); right:0; z-index:8; display:grid; gap:4px; width:min(340px, calc(100vw - 24px)); max-height:360px; overflow:auto; padding:8px; border:1px solid var(--line); border-radius:16px; background:var(--surface); box-shadow:var(--shadow); }
.conversation-history-empty { margin:0; padding:16px; color:var(--muted); font-size:13px; }
.conversation-history-item { display:grid; gap:4px; min-width:0; padding:10px 12px; border:1px solid transparent; border-radius:12px; background:transparent; color:var(--ink); text-align:left; cursor:pointer; }
.conversation-history-item:hover, .conversation-history-item.is-current { border-color:var(--line); background:var(--page); }
.conversation-history-item strong, .conversation-history-item small { overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.conversation-history-item strong { font-size:13px; }
.conversation-history-item small { color:var(--muted); font-size:12px; }
.conversation-history-item > span { display:flex; justify-content:space-between; gap:8px; color:var(--muted); font-size:11px; }
.conversation-history-item em { color:var(--brand); font-style:normal; }
.conversation-history-item:disabled { opacity:.55; cursor:not-allowed; }
.chat-identity-title { display:flex; align-items:center; flex-wrap:wrap; gap:6px 10px; min-width:0; }.chat-status-bar { padding:0; min-width:0; }.chat-status-bar:has(.is-blocked) { flex-basis:100%; }
.slot-strip { display:flex; gap:8px; margin:0; padding:8px 16px; overflow-x:auto; list-style:none; border-bottom:1px solid var(--line); background:var(--surface); }
.slot-strip li { flex:0 0 auto; max-width:260px; padding:6px 10px; border-radius:999px; background:var(--page); }
.slot-strip span, .slot-strip strong { display:inline; }
.slot-strip span { margin-right:6px; color:var(--muted); font-size:12px; }
.slot-strip strong { font-size:12px; font-weight:600; }
.slot-strip .is-current { background:var(--brand-soft); }
.slot-strip .is-current strong { color:var(--brand); }
.slot-strip .is-off { opacity:.65; }
.proposal-chat-body { display:grid; grid-template-columns:minmax(0, 1fr); gap:16px; align-items:start; min-width:0; padding:16px; }
.proposal-chat.has-queue-preview .proposal-chat-body { grid-template-columns:minmax(0, 1fr) minmax(240px, 300px); }
.proposal-chat-preview { min-width:0; }
.proposal-chat-main { display:flex; flex-direction:column; min-width:0; }
.proposal-chat-messages { display:flex; min-width:0; min-height:220px; max-height:clamp(260px, 50dvh, 560px); overflow-y:auto; overscroll-behavior:contain; padding:12px; border-radius:16px; background:var(--page); }
.chat-conversation-group { width:100%; max-width:820px; margin:0 auto; }
.chat-message-list { display:grid; gap:10px; padding:0; margin:0; list-style:none; }
.chat-row { display:flex; min-width:0; }
.chat-row.is-user { justify-content:flex-end; }
.chat-row.is-welcome { display:block; }
.chat-bubble { max-width:min(88%, 680px); padding:10px 14px; border-radius:16px; background:var(--surface); color:var(--ink); white-space:pre-wrap; overflow-wrap:anywhere; font-size:15px; line-height:1.55; box-shadow:0 2px 10px rgba(20,35,27,.04); }
.is-user .chat-bubble { background:var(--brand-soft); box-shadow:none; }
.bubble-welcome { max-width:none; padding:4px 0; background:transparent; box-shadow:none; }
.chat-bubble strong { display:block; font-size:16px; font-weight:650; }
.chat-bubble p { margin:7px 0 0; color:var(--muted); font-size:14px; }
.chat-welcome-help { margin-top:8px; }
.chat-welcome-help > summary { display:flex; align-items:center; min-height:44px; color:var(--brand); cursor:pointer; font-size:13px; }
.chat-example { padding:8px 10px; border-radius:10px; background:var(--surface); color:var(--ink)!important; font-size:13px!important; }
.contextual-reply { color:var(--ink)!important; }
.mode-quick-choices { display:grid; grid-template-columns:repeat(3, minmax(0, 1fr)); gap:8px; margin-top:12px; }
.mode-quick-choices button { min-width:0; min-height:56px; padding:8px 10px; border:1px solid var(--line); border-radius:12px; background:var(--surface); color:var(--ink); text-align:left; cursor:pointer; }
.mode-quick-choices button:hover:not(:disabled) { border-color:var(--brand); background:var(--brand-soft); }
.mode-quick-choices button:disabled { opacity:.55; cursor:not-allowed; }
.mode-quick-choices button strong { font-size:13px; }
.mode-quick-choices button small { display:block; margin-top:3px; color:var(--muted); font-size:11px; line-height:1.35; }
.chat-bubble p[role=alert] { color:var(--danger); }
.chat-bubble p[role=alert] a { display:inline-flex; margin-left:8px; font-weight:600; }
.chat-bubble ul { margin:8px 0 0; padding-left:18px; }
.bubble-thinking { color:var(--muted); background:transparent; box-shadow:none; }
.bubble-error { background:var(--danger-soft); color:var(--danger); }
.bubble-error p { color:inherit; }
.bubble-saved, .bubble-ready { background:var(--success-soft); }
.bubble-artifact { width:min(100%, 720px); max-width:100%; padding:0; background:transparent; box-shadow:none; }
.bubble-artifact > section { margin:0!important; }
.chat-pending-label { display:block; margin-top:6px; color:var(--muted); font-size:12px; }
.chat-thinking-dot { display:inline-block; width:8px; height:8px; margin-right:8px; border-radius:50%; background:var(--brand); animation:chat-pulse 1.2s ease-in-out infinite; }
.proposal-trace { margin-top:8px; padding:0 12px; border:1px solid var(--line); border-radius:12px; background:var(--surface); }
.proposal-trace summary { display:flex; justify-content:space-between; align-items:center; min-height:42px; cursor:pointer; font-size:12px; font-weight:600; }
.proposal-trace summary span + span { color:var(--muted); font-weight:500; }
.proposal-trace-note { margin:0 0 8px; color:var(--muted); font-size:12px; }
.proposal-trace-list { display:grid; gap:8px; padding:0 0 10px; margin:0; list-style:none; }
.trace-item { display:grid; grid-template-columns:22px minmax(0, 1fr) auto; gap:8px; align-items:start; }
.trace-index { width:20px; height:20px; display:grid; place-items:center; border-radius:50%; background:var(--brand-soft); color:var(--brand); font-size:11px; font-weight:600; }
.trace-item strong { font-size:12px; }
.trace-item p, .trace-item time { margin:4px 0 0; color:var(--muted); font-size:11px; }
.trace-item time { white-space:nowrap; }
.proposal-chat :deep(button:focus-visible), .proposal-chat :deep(summary:focus-visible), .proposal-chat :deep(a:focus-visible) { outline:3px solid var(--brand); outline-offset:2px; }
@keyframes chat-pulse { 50% { opacity:.35; } }
@media (max-width:1024px) {
  .proposal-chat.has-queue-preview .proposal-chat-body { grid-template-columns:minmax(0, 1fr); }
  .proposal-chat-messages { min-height:200px; max-height:48vh; }
  .proposal-chat-preview { order:-1; }
}
@media (max-width:600px) {
  .proposal-chat-heading { display:grid; grid-template-columns:minmax(0,1fr) auto; gap:6px 8px; padding:8px 12px; }
  .proposal-chat-identity { gap:8px; }
  .proposal-chat-avatar { display:none; }
  .proposal-chat-heading h2 { font-size:16px; }
  .proposal-chat-heading p { display:none; }
  .chat-header-actions { display:contents; }
  .chat-conversation-actions { grid-column:2; grid-row:1; gap:4px; }
  .chat-credential-toolbar { grid-column:1/-1; grid-row:2; }
  .chat-credential-toolbar :deep(.plan-credential-control) { width:100%; justify-content:space-between; }
  .chat-new-button, .conversation-history > summary { padding:0 8px; font-size:12px; }
  .conversation-history-menu { position:fixed; left:12px; right:12px; top:auto; bottom:12px; width:auto; max-height:50dvh; }
  .proposal-chat-body { gap:10px; padding:10px; }
  .proposal-chat-messages { min-height:180px; max-height:clamp(180px,32dvh,280px); padding:12px; }
  .chat-bubble { max-width:100%; }
  .mode-quick-choices { grid-template-columns:repeat(3,minmax(0,1fr)); gap:6px; margin-top:8px; }
  .mode-quick-choices button { min-height:60px; padding:6px; }
  .mode-quick-choices button small { font-size:12px; }
  .trace-item { grid-template-columns:20px minmax(0, 1fr); }
  .trace-item time { grid-column:2; }
}
@media (max-width:380px) {
  .proposal-chat-avatar,.chat-action-label { display:none; }
  .chat-new-button { width:44px; padding:0; }
  .chat-status-bar :deep(.agent-credential-gate.is-ready .agent-gate-copy) { position:absolute; width:1px; height:1px; overflow:hidden; clip:rect(0,0,0,0); }
  .proposal-chat-heading { padding:4px 8px; }
  .proposal-chat-body { padding:8px; gap:8px; }
  .proposal-chat-messages { min-height:156px; padding:8px; }
  .chat-status-bar :deep(.agent-credential-gate.is-ready) { padding:6px 0; }
}
@media (prefers-reduced-motion: reduce) { .chat-thinking-dot { animation:none; } }
</style>
