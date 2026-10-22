<script setup>
import { actionLabel, logLevels, logTime, moduleLabel } from '../../utils/runtimeLogs.js';
defineProps({ events: { type: Array, required: true }, selectedId: Number });
const emit = defineEmits(['select']);
</script>
<template>
  <ol class="runtime-events" aria-label="运行日志列表">
    <li v-for="event in events" :key="event.event_id" class="runtime-event" :class="[{ 'is-selected': selectedId === event.event_id }, `level-${event.level}`]">
      <div class="event-time"><time>{{ logTime(event.at_utc_ms) }}</time><span class="event-level">{{ logLevels[event.level] }}</span></div>
      <div class="event-content"><div class="event-title"><strong>{{ actionLabel(event.action) }}</strong><span>{{ moduleLabel(event.module) }}</span><small v-if="event.elapsed_ms !== null">{{ event.elapsed_ms }} ms</small></div><code v-if="event.code" class="event-code">{{ event.code }}</code><p class="event-context"><span v-if="event.user_id">用户 {{ event.user_id }}</span><span v-if="event.details.stage">阶段 {{ event.details.stage }}</span><span v-if="event.details.http_status">HTTP {{ event.details.http_status }}</span><span v-if="event.details.attempt">第 {{ event.details.attempt }} 次</span></p></div>
      <button class="secondary-button" type="button" :aria-label="`查看第 ${event.event_id} 条日志详情`" :aria-pressed="selectedId === event.event_id" @click="emit('select', event.event_id)">查看详情</button>
      <slot name="detail" :event="event" />
    </li>
  </ol>
</template>
<style scoped>
.runtime-events{list-style:none;padding:0;margin:0;display:grid;gap:10px;min-width:0}.runtime-event{display:grid;grid-template-columns:132px minmax(0,1fr) auto;align-items:center;gap:16px;padding:16px;border:1px solid var(--line);border-left:3px solid var(--line);border-radius:12px;background:var(--surface);min-width:0}.runtime-event.level-warning{border-left-color:var(--warning)}.runtime-event.level-error{border-left-color:var(--danger)}.runtime-event.is-selected{background:var(--brand-soft);border-color:var(--brand)}.event-time{display:grid;gap:8px;justify-items:start}.event-time time{font-size:12px;color:var(--muted);font-variant-numeric:tabular-nums}.event-level{padding:2px 7px;border-radius:5px;background:var(--page);font-size:11px}.level-warning .event-level{color:var(--warning)}.level-error .event-level{color:var(--danger)}.event-content{min-width:0}.event-title{display:flex;align-items:center;gap:10px;flex-wrap:wrap}.event-title strong{font-size:14px}.event-title span,.event-title small{color:var(--muted);font-size:12px}.event-code{display:block;margin-top:6px;font-size:12px;overflow-wrap:anywhere;color:var(--ink)}.event-context{display:flex;gap:12px;flex-wrap:wrap;margin:6px 0 0;font-size:11px;color:var(--muted);overflow-wrap:anywhere}.runtime-event button{min-height:44px;font-size:12px}.runtime-event> :deep(.log-detail-state),.runtime-event> :deep(.log-detail){grid-column:1/-1}@media(max-width:650px){.runtime-event{grid-template-columns:minmax(0,1fr);gap:8px;padding:10px}.event-time{display:flex;align-items:center;justify-content:space-between}.runtime-event button{justify-self:start;min-height:44px}.event-title{gap:8px}}
</style>
