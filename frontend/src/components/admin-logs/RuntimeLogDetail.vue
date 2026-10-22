<script setup>
import { computed } from 'vue';
import { actionLabel, logLevels, logTime } from '../../utils/runtimeLogs.js';
const props = defineProps({ detail: { type: Object, required: true } });
const emit = defineEmits(['close']);
const identifiers = computed(() => [
  ['用户', props.detail.event.user_id], ['凭据编号', props.detail.event.credential_id],
  ['请求编号', props.detail.event.request_id], ['会话编号', props.detail.event.conversation_id], ['执行任务', props.detail.event.run_id],
].filter(item => item[1]));
const attributes = computed(() => Object.entries(props.detail.event.details || {}).filter(([key]) => !['frames', 'exception_type'].includes(key)));
</script>
<template>
  <section class="panel log-detail" aria-label="日志详情">
    <header class="log-detail-heading"><div><p class="eyebrow">EVENT #{{ detail.event.event_id }}</p><h2>{{ actionLabel(detail.event.action) }}</h2><p class="muted">{{ logTime(detail.event.at_utc_ms) }} · {{ logLevels[detail.event.level] }}</p></div><button class="secondary-button" type="button" @click="emit('close')">关闭详情</button></header>
    <p v-if="detail.event.code" class="detail-error-code"><code>{{ detail.event.code }}</code></p>
    <dl class="detail-facts"><div v-for="item in identifiers" :key="item[0]"><dt>{{ item[0] }}</dt><dd><code>{{ item[1] }}</code></dd></div><div v-for="[key, value] in attributes" :key="key"><dt>{{ key }}</dt><dd>{{ value }}</dd></div></dl>
    <section v-if="detail.event.details.exception_type" class="safe-stack"><h3>代码位置 · {{ detail.event.details.exception_type }}</h3><p class="muted">仅展示调用位置，不包含异常原文或局部变量。</p><ol><li v-for="(frame, index) in detail.event.details.frames" :key="index"><code>{{ frame.file }}:{{ frame.line }}</code><span>{{ frame.function }}</span></li></ol></section>
    <section v-if="detail.execution" class="related-events"><h3>持久化执行阶段 · {{ detail.execution.state }}</h3><p class="muted">{{ detail.execution.target_date }} · 来自执行器业务记录</p><ol><li v-for="stage in detail.execution.stages" :key="`${stage.round_number}-${stage.candidate_index}-${stage.stage_key}`"><time>{{ logTime(stage.started_at_utc_ms) }}</time><div><strong>{{ stage.stage_key }}</strong><span>第 {{ stage.round_number }} 轮 · 候选 {{ stage.candidate_index }} · {{ stage.outcome }} · {{ stage.elapsed_ms }} ms</span><code v-if="stage.safe_code">{{ stage.safe_code }}</code></div></li></ol><p v-if="detail.execution.truncated" class="muted">这里只显示最近 500 个执行阶段。</p></section>
    <section class="related-events"><h3>关联事件时间线</h3><p class="muted">同一执行任务、请求或会话中的记录。</p><ol><li v-for="event in detail.related" :key="event.event_id"><time>{{ logTime(event.at_utc_ms) }}</time><div><strong>{{ actionLabel(event.action) }}</strong><span>{{ event.details.stage || event.details.endpoint || event.details.phase || logLevels[event.level] }}<template v-if="event.elapsed_ms !== null"> · {{ event.elapsed_ms }} ms</template></span><code v-if="event.code">{{ event.code }}</code></div></li></ol><p v-if="detail.related_truncated" class="muted">这里只显示最近 100 条关联日志。</p></section>
  </section>
</template>
<style scoped>
.log-detail{padding:22px;display:grid;gap:18px;min-width:0}.log-detail-heading{display:flex;justify-content:space-between;gap:12px;flex-wrap:wrap;align-items:start}.log-detail-heading h2{font-size:18px;margin:4px 0}.log-detail-heading p{margin:0;font-size:12px}.detail-error-code{margin:0;overflow-wrap:anywhere;color:var(--danger)}.detail-facts{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px;margin:0}.detail-facts>div{min-width:0}.detail-facts dt{font-size:12px;color:var(--muted)}.detail-facts dd{margin:4px 0 0;overflow-wrap:anywhere;font-size:12px}.safe-stack h3,.related-events h3{font-size:14px;margin:0 0 8px}.safe-stack p,.related-events p{font-size:12px;margin:0 0 12px}.safe-stack ol{margin:0;padding:14px 14px 14px 32px;border-radius:10px;background:var(--page);font-size:12px}.safe-stack li{padding:4px 0;overflow-wrap:anywhere}.safe-stack li span{display:block;color:var(--muted);margin-top:3px}.related-events ol{padding:0;margin:0;list-style:none;display:grid;gap:0}.related-events li{display:grid;grid-template-columns:126px minmax(0,1fr);gap:12px;padding:12px 0;border-bottom:1px solid var(--line);font-size:12px}.related-events time{color:var(--muted);font-variant-numeric:tabular-nums}.related-events li div{display:grid;gap:4px;min-width:0;overflow-wrap:anywhere}.related-events li strong{font-weight:500}.related-events li span{color:var(--muted)}@media(max-width:650px){.log-detail{padding:16px}.detail-facts{grid-template-columns:minmax(0,1fr)}.related-events li{grid-template-columns:minmax(0,1fr);gap:6px}}
</style>
