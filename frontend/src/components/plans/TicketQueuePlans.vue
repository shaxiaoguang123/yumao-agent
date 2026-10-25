<script setup>
import { computed, ref, shallowRef, watch, onUnmounted } from 'vue';
import AppIcon from '../AppIcon.vue';
import ManualQueuePreview from './ManualQueuePreview.vue';
import ExecutionSnapshotPanel from './ExecutionSnapshotPanel.vue';
import { queueEntries } from '../../composables/useManualQueue.js';
import { visibleManualQueuePlans } from '../../utils/planQueueVisibility.js';
import { executionStateLabels } from '../../utils/executionStatus.js';
const props=defineProps({queues:{type:Array,default:()=>[]},dateFilter:{type:String,default:''},calendarState:Object,courtNames:Array,api:Object,session:Object,busy:Boolean,overview:Boolean,active:{type:Boolean,default:true}});
const emit=defineEmits(['select','history','changed']);
const deleting=ref(''),mutating=ref(false),error=ref('');
const execution=shallowRef({}),executionRefreshKey=ref(0);
let epoch=0,alive=true;
const visible=computed(()=>props.overview?props.queues:visibleManualQueuePlans(props.queues,{dateFilter:props.dateFilter,businessDate:props.calendarState?.business_date||''}));
const inWindow=q=>(props.calendarState?.queryable_target_dates||[]).includes(q.target_date)&&q.can_open_selection!==false;
function stateLabel(q){
 if(q.lifecycle)return q.lifecycle.label;
 if(!q.candidates.length)return '已清空';
 const result=execution.value[q.plan_id];
 if(result?.status==='ready'&&result.run){
  const run=result.run;
  if(run.source_version!==q.version||run.source_revision_id!==q.current_revision_id)
   return `队列已修改 · 执行记录来自 v${run.source_version}`;
  return executionStateLabels[run.state]||'状态未知';
 }
 if(result?.status==='error')return '执行状态读取失败';
 if(q.plan_status==='expired'||q.target_date<(props.calendarState?.business_date||''))return '已过期';
 if(q.credential_id){
  if(!result||result.status==='loading')return '读取执行状态…';
  if(result.status==='unavailable')return '执行状态不可用';
 }
 return inWindow(q)?'未执行':'窗口外 · 未执行';
}
const historical=q=>q.lifecycle?.is_current_revision===false;
function timeText(value){return Number.isSafeInteger(value)?new Intl.DateTimeFormat('zh-CN',{timeZone:props.calendarState?.business_timezone_name||'Asia/Shanghai',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hour12:false}).format(value):'—';}
function rememberExecution(queue,result){execution.value={...execution.value,[queue.plan_id]:result};}
watch(()=>props.queues,()=>{execution.value={};executionRefreshKey.value++;},{flush:'sync'});
const valid=generation=>alive&&generation===epoch&&props.session?.status==='authenticated';
watch(()=>[props.session?.status,props.session?.user?.user_id,props.session?.csrfToken,props.session?.invalidationEpoch],()=>{epoch++;deleting.value='';mutating.value=false;error.value='';execution.value={};},{flush:'sync'});
function selectQueue(queue){if(queue.credential_id)emit('select',queue.target_date,queue.credential_id);}
async function remove(q){if(mutating.value||props.busy)return;const generation=epoch;mutating.value=true;error.value='';try{await props.api.removeQueue(q.target_date,q.version,q.credential_id??null);if(valid(generation)){deleting.value='';emit('changed',q.target_date);}}catch(e){if(valid(generation))error.value=e?.status===409?'计划版本已变化，请重新读取后删除。':'删除结果未确认，请重新读取计划核对。';}finally{if(valid(generation))mutating.value=false;}}
onUnmounted(()=>{alive=false;epoch++;});
</script>
<template>
 <section v-if="visible.length||error" class="ticket-queue-plans" aria-label="人工抢票计划">
  <p v-if="error" class="form-error" role="alert">{{ error }}</p>
  <article v-for="queue in visible" :key="queue.record_id||queue.plan_id" class="ticket-queue-card"><header class="ticket-card-heading"><strong>{{ queue.target_date }}</strong><span class="ticket-version">v{{ queue.version }}</span><span class="ticket-state" role="status" :class="{'is-expired':stateLabel(queue)==='已过期','is-success':stateLabel(queue)===executionStateLabels.succeeded}">{{ stateLabel(queue) }}</span><span v-if="!queue.credential_id" class="ticket-scope">历史未关联凭据</span><div class="ticket-card-actions"><button type="button" :disabled="busy||mutating||historical(queue)||!queue.credential_id||!inWindow(queue)" :title="!queue.credential_id?'历史计划未关联凭据':inWindow(queue)?'继续到选择预约':'当天不在可查询窗口'" :aria-label="`${queue.target_date}继续选择`" @click="selectQueue(queue)"><AppIcon name="court" /></button><button type="button" :disabled="busy||mutating||historical(queue)||!queue.credential_id" :title="queue.credential_id?'在选择预约界面编辑':'历史计划未关联凭据，无法按 Token 编辑'" :aria-label="`编辑${queue.target_date}队列`" @click="selectQueue(queue);deleting='' "><AppIcon name="edit" /></button><button type="button" :disabled="mutating" :aria-label="`${queue.target_date}版本历史`" @click="emit('history',queue.target_date,queue.credential_id??null)"><AppIcon name="clock" /></button><button type="button" :disabled="busy||mutating||historical(queue)" :aria-label="`删除${queue.target_date}队列`" @click="deleting=queue.record_id||queue.plan_id;error='' "><AppIcon name="trash" /></button></div></header>
   <div v-if="deleting===(queue.record_id||queue.plan_id)" class="ticket-delete-confirm"><span>删除该日计划？历史修订会保留。</span><button type="button" class="danger-button" :disabled="mutating" @click="remove(queue)">确认删除</button><button type="button" class="text-button" :disabled="mutating" @click="deleting=''">取消</button></div>
   <p v-if="queue.lifecycle" class="ticket-times"><span>开抢窗口：{{ timeText(queue.lifecycle.opening_at_utc_ms) }} · {{ (calendarState?.business_timezone_name||'Asia/Shanghai')==='Asia/Shanghai'?'北京时间':calendarState.business_timezone_name }}</span><span v-if="queue.lifecycle.completed_at_utc_ms">执行结束：{{ timeText(queue.lifecycle.completed_at_utc_ms) }}</span><span v-if="historical(queue)" class="ticket-history-label">历史执行 v{{ queue.version }} · 当前队列 v{{ queue.lifecycle.current_version }}</span></p>
   <p v-if="queue.success" class="ticket-success-result">预约成功：{{ queue.success.court_preference }} · {{ queue.success.start_time }}–{{ queue.success.end_time }}<small>{{ timeText(queue.success.confirmed_at_utc_ms) }} 查单确认</small></p>
   <ManualQueuePreview v-if="queue.candidates.length" :entries="queueEntries(queue)" readonly /><p v-else class="ticket-empty">候选已清空，可以查看历史版本。</p>
   <ExecutionSnapshotPanel v-if="queue.credential_id&&queue.candidates.length" :api="api" :credential-id="queue.credential_id" :target-date="queue.target_date" :source-plan-id="queue.plan_id" :source-revision-id="overview?queue.current_revision_id:''" :summary="queue.lifecycle" :lazy="overview" :refresh-key="executionRefreshKey" :active="active" :session="session" @status-change="rememberExecution(queue,$event)" />
  </article>
 </section>
</template>
<style scoped>
.ticket-queue-plans{display:grid;gap:16px;min-width:0}.ticket-queue-card{border:1px solid var(--line);border-radius:8px;padding:16px;background:var(--surface)}.ticket-card-heading{display:flex;align-items:center;gap:8px;margin-bottom:8px;min-width:0;font-size:14px}.ticket-version{font-size:12px;color:var(--muted)}.ticket-state{font-size:12px;padding:8px 8px;background:var(--brand-soft);color:var(--brand);border-radius:8px;white-space:nowrap}.ticket-state.is-expired{color:var(--warning);background:var(--warning-soft)}.ticket-card-actions{display:flex;gap:8px;margin-left:auto}.ticket-card-actions button{width:44px;min-height:var(--control-height);display:grid;place-items:center;padding:8px;border:0;background:transparent;color:var(--muted);border-radius:8px;cursor:pointer}.ticket-card-actions button:disabled{opacity:.3;cursor:default}.ticket-card-actions button:hover:not(:disabled){background:var(--brand-soft)}.ticket-card-actions .app-icon{width:17px;height:17px}.ticket-empty{font-size:13px;color:var(--muted);padding:16px 0;margin:0}.ticket-queue-card :deep(.queue-preview){grid-template-columns:repeat(2,minmax(0,1fr));gap:8px}.ticket-delete-confirm{display:flex;gap:8px;align-items:center;flex-wrap:wrap;font-size:13px;margin-bottom:8px}.ticket-delete-confirm button{min-height:var(--control-height);font-size:12px}@media(max-width:600px){.ticket-card-heading{flex-wrap:wrap}.ticket-card-actions button{width:44px;min-height:var(--control-height)}.ticket-queue-card :deep(.queue-preview){grid-template-columns:minmax(0,1fr)}}
</style>

<style scoped>
.ticket-times{display:flex;flex-wrap:wrap;gap:4px 16px;font-size:12px;color:var(--muted);margin:0 0 12px}.ticket-history-label{color:var(--warning)}.ticket-success-result{padding:10px 12px;border-radius:12px;background:var(--success-soft);color:var(--success);font-size:14px;font-weight:600}.ticket-success-result small{display:block;margin-top:4px;font-size:12px;font-weight:400}
.ticket-scope{color:var(--muted);font-size:11px}
.ticket-state{max-width:100%;white-space:normal;overflow-wrap:anywhere}
.ticket-state.is-success{color:var(--success);background:var(--success-soft)}
</style>
