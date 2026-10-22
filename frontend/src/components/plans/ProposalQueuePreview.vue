<script setup>
import { computed } from 'vue';

const props = defineProps({
  slots: { type: Array, default: () => [] },
  proposal: { type: Object, default: null },
});

const fields = computed(() => Object.fromEntries(props.slots.map((slot) => [slot.field, slot])));
const groups = computed(() => [
  { id: '2h', minutes: 120, title: '2小时队列', windows: fields.value.windows_2h, courts: fields.value.courts_2h },
  { id: '1h', minutes: 60, title: '1小时队列', windows: fields.value.windows_1h, courts: fields.value.courts_1h },
]);
const dateLabel = computed(() => fields.value.target_date?.display || '待确认日期');
const modeLabel = computed(() => fields.value.booking_mode?.display || '待选择队列类型');
const missingCount = computed(() => props.slots.filter((slot) => slot.active && slot.status !== 'proposed' && slot.status !== 'verified').length);

function chips(value) {
  return value ? value.split(/[、,，]/).map((item) => item.trim()).filter(Boolean) : [];
}

function candidates(minutes) {
  return (props.proposal?.entries || []).filter((entry) => entry.duration_minutes === minutes);
}
</script>

<template>
  <aside class="queue-preview" aria-label="预约队列预览">
    <details class="queue-preview-details">
      <summary>
        <span><strong>队列预览</strong><small>{{ dateLabel }} · {{ modeLabel }}</small></span>
        <span class="queue-preview-count">{{ proposal ? `共 ${proposal.entry_count} 项` : (missingCount ? `还缺 ${missingCount} 项` : '已收集') }}</span>
      </summary>
      <div class="queue-preview-content">
        <section v-for="group in groups" :key="group.id" class="queue-preview-group" :aria-label="group.title">
          <header><h3>{{ group.title }}</h3><span v-if="group.windows?.active === false">本次不选</span><span v-else-if="group.windows?.status === 'invalid' || group.courts?.status === 'invalid'">需修正</span><span v-else-if="group.windows?.display && group.courts?.display">已填写</span><span v-else>待填写</span></header>
          <template v-if="candidates(group.minutes).length">
            <ul class="queue-candidate-list">
              <li v-for="(entry, index) in candidates(group.minutes)" :key="`${entry.start_time}-${entry.court_preference}-${index}`">
                <span>{{ entry.start_time }}–{{ entry.end_time }}</span><strong>{{ entry.court_preference }}</strong>
              </li>
            </ul>
          </template>
          <template v-else>
            <div class="queue-preview-field"><span>时间</span><div class="queue-preview-chips" aria-label="已选时间段">
              <span v-for="item in chips(group.windows?.display)" :key="item" class="queue-preview-chip">{{ item }}</span>
              <small v-if="!group.windows?.display">{{ group.windows?.active === false ? '—' : '未选择' }}</small>
            </div></div>
            <div class="queue-preview-field"><span>场地</span><div class="queue-preview-chips" aria-label="已选场地">
              <span v-for="item in chips(group.courts?.display)" :key="item" class="queue-preview-chip">{{ item }}</span>
              <small v-if="!group.courts?.display">{{ group.courts?.active === false ? '—' : '未选择' }}</small>
            </div></div>
          </template>
        </section>
      </div>
      <p class="queue-preview-note">1小时和2小时分别确认时段与场地。</p>
    </details>
  </aside>
</template>

<style scoped>
.queue-preview { min-width: 0; }
.queue-preview-details { border: 1px solid var(--line); border-radius: 16px; background: var(--surface); }
.queue-preview-details > summary { display: flex; align-items: center; justify-content: space-between; gap: 8px; min-height: 56px; padding: 8px 12px; cursor: pointer; list-style: none; }
.queue-preview-details > summary::-webkit-details-marker { display: none; }
.queue-preview-details > summary::after { content:""; flex:none; width:7px; height:7px; border-right:1.5px solid var(--muted); border-bottom:1.5px solid var(--muted); transform:rotate(45deg); margin:0 2px 4px 0; }
.queue-preview-details[open] > summary::after { transform:rotate(225deg); margin-top:5px; }
.queue-preview-details > summary > span:first-child { min-width: 0; }
.queue-preview-details strong, .queue-preview-details small { display: block; }
.queue-preview-details small { margin-top: 4px; color: var(--muted); font-size: 12px; }
.queue-preview-count { margin-left:auto; flex: none; color: var(--brand); font-size: 12px; font-weight: 650; }
.queue-preview-content { display: grid; gap: 8px; padding: 0 8px 8px; }
.queue-preview-group { min-width: 0; padding: 8px; border-radius: 12px; background: var(--page); }
.queue-preview-group header { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
.queue-preview-group h3 { margin: 0; font-size: 13px; }
.queue-preview-group header > span { color: var(--muted); font-size: 11px; white-space: nowrap; }
.queue-preview-field { display: grid; gap: 4px; margin-top: 8px; }
.queue-preview-field > span { color: var(--muted); font-size: 11px; }
.queue-preview-chips { display: flex; gap: 6px; min-width: 0; overflow-x: auto; padding: 2px 0 4px; overscroll-behavior-inline: contain; scrollbar-width: thin; }
.queue-preview-chip { flex: none; padding: 4px 8px; border-radius: 999px; background: var(--surface); color: var(--ink); font-size: 12px; white-space: nowrap; }
.queue-preview-chips small { color: var(--muted); font-size: 12px; }
.queue-candidate-list { display: grid; gap: 4px; max-height: 176px; overflow: auto; margin: 8px 0 0; padding: 0; list-style: none; }
.queue-candidate-list li { display: flex; justify-content: space-between; gap: 8px; padding: 6px 8px; border-radius: 8px; background: var(--surface); font-size: 12px; font-variant-numeric: tabular-nums; }
.queue-candidate-list strong { white-space: nowrap; }
.queue-preview-note { margin: 0; padding: 0 8px 8px; color: var(--muted); font-size: 11px; line-height: 1.5; }
.queue-preview :deep(summary:focus-visible) { outline: 3px solid var(--brand); outline-offset: 2px; }
@media(max-width:1024px){.queue-preview-details{background:var(--brand-soft)}.queue-preview-details>summary{min-height:56px}.queue-preview-count{padding:4px 8px;border-radius:999px;background:var(--surface)}}
@media(max-width:420px){.queue-preview-details>summary{padding:6px 10px}.queue-preview-details strong{font-size:14px}.queue-preview-count{padding:4px 6px}.queue-candidate-list li{align-items:flex-start;flex-direction:column}}
</style>
