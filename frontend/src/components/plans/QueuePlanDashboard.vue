<script setup>
import { computed, ref, watch } from 'vue';
import AppIcon from '../AppIcon.vue';
import TicketQueuePlans from './TicketQueuePlans.vue';
import { useQueueOverview } from '../../composables/useQueueOverview.js';

const props = defineProps({ api:Object, session:Object, credentialId:String, calendarState:Object, active:Boolean, busy:Boolean, refreshKey:Number });
const emit = defineEmits(['select', 'history', 'changed', 'count-change']);
const targetDate = defineModel('dateFilter', { default:'' });
const category = ref('pending');
const categories = [
  { value:'pending', label:'待执行／执行中' }, { value:'succeeded', label:'已成功' },
  { value:'attention', label:'需处理' }, { value:'all', label:'全部' },
];
const state = useQueueOverview(props.api, props.session, () => ({ credentialId:props.credentialId,
  category:category.value, targetDate:targetDate.value, active:props.active, refreshKey:props.refreshKey }));
const sortHint = computed(() => category.value === 'pending' ? '执行中置顶 · 开抢时间由近到远' : category.value === 'all' ? '最近变动优先 · 包含历史记录' : '最近结果优先 · 包含历史记录');
watch(() => state.counts, counts => emit('count-change', counts), { immediate:true });
function changed(date) { emit('changed', date); }
</script>

<template>
  <section class="queue-dashboard" aria-label="抢票计划管理">
    <div class="ticket-filter-bar">
      <div class="ticket-filter-credential"><slot name="credentials" /></div>
      <label class="ticket-filter-date"><AppIcon name="calendar" /><input v-model="targetDate" type="date" aria-label="抢票计划日期" /></label>
      <button class="text-button ticket-filter-all" type="button" @click="targetDate=''">全部日期</button>
      <button class="text-button ticket-refresh" type="button" aria-label="重新读取抢票计划" :disabled="state.status==='loading'||busy" @click="state.refresh"><AppIcon name="refresh" /></button>
      <div class="queue-status-filters" role="group" aria-label="计划状态筛选">
        <button v-for="item in categories" :key="item.value" type="button" :data-testid="`queue-filter-${item.value}`" :aria-pressed="category===item.value" @click="category=item.value">
          {{ item.label }}<span>{{ state.counts?.[item.value] ?? '—' }}</span>
        </button>
      </div>
    </div>
    <div class="queue-list-summary"><span>{{ sortHint }}</span><span v-if="state.counts">{{ state.total }} 条记录</span></div>
    <p v-if="!credentialId" class="muted">请先选择预约凭据。</p>
    <p v-else-if="state.status==='loading'&&!state.queues.length" class="status-loading" role="status">正在读取计划与执行状态…</p>
    <p v-if="state.message" class="form-error" role="alert">{{ state.message }}<button type="button" class="text-button" @click="state.refresh">重新读取</button></p>
    <TicketQueuePlans :queues="state.queues" overview :calendar-state="calendarState" :api="api" :session="session" :active="active" :busy="busy"
      @select="(...args)=>emit('select',...args)" @history="(...args)=>emit('history',...args)" @changed="changed" />
    <p v-if="state.status==='ready'&&!state.queues.length" class="plan-empty-state">{{ category==='pending'?'暂无待执行计划。':category==='succeeded'?'暂无成功记录。':category==='attention'?'暂无需要处理的计划。':'暂无抢票计划。' }}<slot name="empty-action" /></p>
    <button v-if="state.nextPage" class="secondary-button queue-load-more" type="button" :disabled="state.status==='loading'" @click="state.more">{{ state.status==='loading'?'正在加载…':'加载更多记录' }}</button>
  </section>
</template>

<style scoped>
.queue-dashboard{display:grid;gap:12px;min-width:0}
.ticket-filter-bar{display:flex;align-items:center;gap:8px;flex-wrap:wrap;padding:12px;border:1px solid var(--line);border-radius:16px;background:var(--surface)}
.ticket-filter-credential{min-width:0;max-width:100%}.ticket-filter-date{display:flex;align-items:center;gap:6px;min-width:0;margin-left:auto;color:var(--muted)}
.ticket-filter-date input{width:155px;min-height:44px;max-width:100%;padding:8px;border:1px solid var(--line);border-radius:12px;background:var(--surface);color:var(--ink)}
.ticket-refresh{padding:8px;flex:none}.ticket-filter-all{padding-inline:8px}
.queue-status-filters{display:flex;flex-wrap:wrap;gap:4px;width:100%;padding-top:4px}
.queue-status-filters button{display:flex;align-items:center;justify-content:center;gap:6px;min-height:44px;padding:8px 12px;border:0;border-radius:980px;background:transparent;color:var(--muted);font:inherit;font-size:13px;cursor:pointer}
.queue-status-filters button[aria-pressed=true]{background:var(--brand-soft);color:var(--brand)}
.queue-status-filters button:hover{background:var(--apple-hover)}.queue-status-filters span{font-size:11px;font-variant-numeric:tabular-nums}
.queue-list-summary{display:flex;justify-content:space-between;gap:8px;color:var(--muted);font-size:12px}.queue-load-more{justify-self:center}
@media(max-width:600px){.ticket-filter-bar{gap:6px;padding:10px}.ticket-filter-date{margin-left:0;flex:1 1 140px}.ticket-filter-date input{width:100%;font-size:16px}.ticket-filter-credential{flex:1 1 100%}.ticket-filter-credential :deep(.credential-popover){width:100%}.ticket-filter-credential :deep(summary){justify-content:flex-start}.queue-status-filters{display:grid;grid-template-columns:1.6fr 1fr 1fr 1fr;gap:2px}.queue-status-filters button{padding:6px 3px;gap:4px;font-size:12px}.queue-list-summary{font-size:11px}}
</style>
