<script setup>
import { computed, ref, shallowRef, watch, onUnmounted } from 'vue';
import AppIcon from '../AppIcon.vue';
import ManualQueuePreview from './ManualQueuePreview.vue';
import ExecutionSnapshotPanel from './ExecutionSnapshotPanel.vue';
import { orderQueueEntries, queueEntries, queueEntriesFingerprint } from '../../composables/useManualQueue.js';
import { visibleManualQueuePlans } from '../../utils/planQueueVisibility.js';
import { executionStateLabels } from '../../utils/executionStatus.js';
const props=defineProps({queues:{type:Array,default:()=>[]},dateFilter:{type:String,default:''},calendarState:Object,courtNames:Array,api:Object,session:Object,busy:Boolean,overview:Boolean,active:{type:Boolean,default:true}});
const emit=defineEmits(['select','history','changed']);
const deleting=ref(''),mutating=ref(false),error=ref('');
const execution=shallowRef({}),executionRefreshKey=ref(0);
const editingPlanId=ref(''),editingEntries=ref([]),editingBaseVersion=ref(0),editingFingerprint=ref('');
const editError=ref(''),editMessage=ref(''),editMessagePlanId=ref(''),queueOverrides=ref({});
let epoch=0,alive=true;
const visible=computed(()=>props.overview?props.queues:visibleManualQueuePlans(props.queues,{dateFilter:props.dateFilter,businessDate:props.calendarState?.business_date||''}));
const inWindow=q=>(props.calendarState?.queryable_target_dates||[]).includes(q.target_date)&&q.can_open_selection!==false;
const queueId=q=>q.plan_id;
const isEditing=q=>editingPlanId.value===queueId(q);
const queueOverride=q=>queueOverrides.value[queueId(q)];
const queueVersion=q=>Math.max(q.version,queueOverride(q)?.version||0);
const queueRevisionId=q=>queueOverride(q)?.version>q.version?queueOverride(q).revisionId:q.current_revision_id;
function entriesForQueue(q){
 const id=queueId(q),override=queueOverride(q);
 if(isEditing(q))return editingEntries.value;
 return override&&override.version>q.version?override.entries:queueEntries(q);
}
const editingDirty=computed(()=>Boolean(editingPlanId.value)
 &&queueEntriesFingerprint(editingEntries.value)!==editingFingerprint.value);
function clearEdit(){editingPlanId.value='';editingEntries.value=[];editingBaseVersion.value=0;editingFingerprint.value='';editError.value='';}
function cancelEdit(q){const reload=Boolean(editError.value);clearEdit();if(reload&&q)emit('changed',q.target_date);}
function toggleEdit(q){
 if(mutating.value||props.busy)return;
 if(isEditing(q)){cancelEdit(q);return;}
 if(editingPlanId.value||historical(q)||!q.credential_id||typeof props.api?.saveQueue!=='function')return;
 const entries=orderQueueEntries(entriesForQueue(q).map(entry=>({...entry})));
 editingPlanId.value=queueId(q);editingEntries.value=entries;editingBaseVersion.value=queueVersion(q);
 editingFingerprint.value=queueEntriesFingerprint(entries);editError.value='';editMessage.value='';editMessagePlanId.value='';
}
function changeEditingEntries(entries){
 if(!editingPlanId.value)return;
 editingEntries.value=orderQueueEntries(entries);editError.value='';editMessage.value='';
}
async function saveEditing(q){
 if(!isEditing(q)||!editingDirty.value||mutating.value||props.busy)return;
 const generation=epoch,id=queueId(q),targetDate=q.target_date,credentialId=q.credential_id,baseVersion=editingBaseVersion.value;
 const submitted=orderQueueEntries(editingEntries.value);
 mutating.value=true;editError.value='';editMessage.value='';
 try{
  const result=await props.api.saveQueue(targetDate,baseVersion,submitted,credentialId);
  if(!valid(generation)||editingPlanId.value!==id)return;
  const saved=result?.queue,confirmed=saved?queueEntries(saved):[];
  if(!Number.isSafeInteger(saved?.version)||saved.version<baseVersion||saved.version>baseVersion+1
   ||typeof saved.current_revision_id!=='string'||!saved.current_revision_id
   ||queueEntriesFingerprint(confirmed)!==queueEntriesFingerprint(submitted))throw new Error('invalid_queue_response');
  queueOverrides.value={...queueOverrides.value,[id]:{version:saved.version,revisionId:saved.current_revision_id,entries:confirmed}};
  clearEdit();editMessagePlanId.value=id;editMessage.value='队列调整已保存。';emit('changed',targetDate);
 }catch(e){
  if(valid(generation))editError.value=e?.status===409?'队列版本已变化，当前调整未覆盖。请取消后重新读取。':e?.status===400?'队列未保存，请核对候选时间和场地。':'保存结果未确认，当前调整已保留，请重新读取计划核对。';
 }finally{if(valid(generation))mutating.value=false;}
}
function stateLabel(q){
 if(q.lifecycle&&queueVersion(q)===q.version)return q.lifecycle.label;
 if(!q.candidates.length)return '已清空';
 const result=execution.value[q.plan_id];
 if(result?.status==='ready'&&result.run){
  const run=result.run;
  if(run.source_version!==queueVersion(q)||run.source_revision_id!==queueRevisionId(q))
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
watch(()=>props.queues,queues=>{
 execution.value={};executionRefreshKey.value++;
 const current=new Map(queues.map(queue=>[queueId(queue),queue]));
 queueOverrides.value=Object.fromEntries(Object.entries(queueOverrides.value).filter(([id,override])=>{
  const queue=current.get(id);return queue&&queue.version<override.version;
 }));
},{flush:'sync'});
const valid=generation=>alive&&generation===epoch&&props.session?.status==='authenticated';
watch(()=>[props.session?.status,props.session?.user?.user_id,props.session?.csrfToken,props.session?.invalidationEpoch],()=>{epoch++;deleting.value='';mutating.value=false;error.value='';execution.value={};clearEdit();editError.value='';editMessage.value='';editMessagePlanId.value='';queueOverrides.value={};},{flush:'sync'});
function selectQueue(queue){if(queue.credential_id)emit('select',queue.target_date,queue.credential_id);}
async function remove(q){if(mutating.value||props.busy||isEditing(q))return;const generation=epoch;mutating.value=true;error.value='';try{await props.api.removeQueue(q.target_date,queueVersion(q),q.credential_id??null);if(valid(generation)){deleting.value='';emit('changed',q.target_date);}}catch(e){if(valid(generation))error.value=e?.status===409?'计划版本已变化，请重新读取后删除。':'删除结果未确认，请重新读取计划核对。';}finally{if(valid(generation))mutating.value=false;}}
onUnmounted(()=>{alive=false;epoch++;});
</script>
<template>
 <section v-if="visible.length||error" class="ticket-queue-plans" aria-label="人工抢票计划">
  <p v-if="error" class="form-error" role="alert">{{ error }}</p>
  <article v-for="queue in visible" :key="queue.record_id||queue.plan_id" class="ticket-queue-card"><header class="ticket-card-heading"><strong>{{ queue.target_date }}</strong><span class="ticket-version">v{{ queueVersion(queue) }}</span><span class="ticket-state" role="status" :class="{'is-expired':stateLabel(queue)==='已过期','is-success':stateLabel(queue)===executionStateLabels.succeeded}">{{ stateLabel(queue) }}</span><span v-if="!queue.credential_id" class="ticket-scope">历史未关联凭据</span><div class="ticket-card-actions"><button type="button" :disabled="busy||mutating||historical(queue)||!queue.credential_id||!inWindow(queue)||isEditing(queue)" :title="!queue.credential_id?'历史计划未关联凭据':inWindow(queue)?'继续到选择预约':'当天不在可查询窗口'" :aria-label="`${queue.target_date}继续选择`" @click="selectQueue(queue)"><AppIcon name="court" /></button><button type="button" :disabled="busy||mutating||historical(queue)||!queue.credential_id||(!isEditing(queue)&&Boolean(editingPlanId))||typeof api?.saveQueue!=='function'" :title="isEditing(queue)?'取消调整':'调整候选顺序或移除场地'" :aria-label="isEditing(queue)?`取消${queue.target_date}队列调整`:`调整${queue.target_date}队列顺序和场地`" @click="toggleEdit(queue)"><AppIcon name="edit" /></button><button type="button" :disabled="mutating||isEditing(queue)" :aria-label="`${queue.target_date}版本历史`" @click="emit('history',queue.target_date,queue.credential_id??null)"><AppIcon name="clock" /></button><button type="button" :disabled="busy||mutating||historical(queue)||isEditing(queue)" :aria-label="`删除${queue.target_date}队列`" @click="deleting=queue.record_id||queue.plan_id;error='' "><AppIcon name="trash" /></button></div></header>
   <div v-if="deleting===(queue.record_id||queue.plan_id)" class="ticket-delete-confirm"><span>删除该日计划？历史修订会保留。</span><button type="button" class="danger-button" :disabled="mutating" @click="remove(queue)">确认删除</button><button type="button" class="text-button" :disabled="mutating" @click="deleting=''">取消</button></div>
   <p v-if="queue.lifecycle" class="ticket-times"><span>开抢窗口：{{ timeText(queue.lifecycle.opening_at_utc_ms) }} · {{ (calendarState?.business_timezone_name||'Asia/Shanghai')==='Asia/Shanghai'?'北京时间':calendarState.business_timezone_name }}</span><span v-if="queue.lifecycle.completed_at_utc_ms">执行结束：{{ timeText(queue.lifecycle.completed_at_utc_ms) }}</span><span v-if="historical(queue)" class="ticket-history-label">历史执行 v{{ queue.version }} · 当前队列 v{{ queue.lifecycle.current_version }}</span></p>
   <p v-if="queue.success" class="ticket-success-result">预约成功：{{ queue.success.court_preference }} · {{ queue.success.start_time }}–{{ queue.success.end_time }}<small>{{ timeText(queue.success.confirmed_at_utc_ms) }} 查单确认</small></p>
   <ManualQueuePreview v-if="entriesForQueue(queue).length||isEditing(queue)" :entries="entriesForQueue(queue)" :readonly="!isEditing(queue)" :disabled="mutating||busy" @change="changeEditingEntries" /><p v-else class="ticket-empty">候选已清空，可以查看历史版本。</p>
   <div v-if="isEditing(queue)" class="ticket-inline-editor"><p class="muted">在同一时长组内调整顺序，或移除单个候选；保存后生效。</p><p v-if="editError" class="form-error" role="alert">{{ editError }}</p><div class="ticket-inline-editor-actions"><button type="button" class="primary-button" :disabled="mutating||busy||!editingDirty" @click="saveEditing(queue)">{{ mutating?'保存中…':'保存调整' }}</button><button type="button" class="secondary-button" :disabled="mutating" @click="cancelEdit(queue)">取消调整</button></div></div>
   <p v-else-if="editMessagePlanId===queue.plan_id" class="form-success" role="status">{{ editMessage }}</p>
   <ExecutionSnapshotPanel v-if="queue.credential_id&&entriesForQueue(queue).length" :api="api" :credential-id="queue.credential_id" :target-date="queue.target_date" :source-plan-id="queue.plan_id" :source-revision-id="overview?queueRevisionId(queue):''" :summary="queue.lifecycle" :lazy="overview" :refresh-key="executionRefreshKey" :active="active" :session="session" @status-change="rememberExecution(queue,$event)" />
  </article>
 </section>
</template>
<style scoped>
.ticket-queue-plans{display:grid;gap:16px;min-width:0}.ticket-queue-card{border:1px solid var(--line);border-radius:8px;padding:16px;background:var(--surface)}.ticket-card-heading{display:flex;align-items:center;gap:8px;margin-bottom:8px;min-width:0;font-size:14px}.ticket-version{font-size:12px;color:var(--muted)}.ticket-state{font-size:12px;padding:8px 8px;background:var(--brand-soft);color:var(--brand);border-radius:8px;white-space:nowrap}.ticket-state.is-expired{color:var(--warning);background:var(--warning-soft)}.ticket-card-actions{display:flex;gap:8px;margin-left:auto}.ticket-card-actions button{width:44px;min-height:var(--control-height);display:grid;place-items:center;padding:8px;border:0;background:transparent;color:var(--muted);border-radius:8px;cursor:pointer}.ticket-card-actions button:disabled{opacity:.3;cursor:default}.ticket-card-actions button:hover:not(:disabled){background:var(--brand-soft)}.ticket-card-actions .app-icon{width:17px;height:17px}.ticket-empty{font-size:13px;color:var(--muted);padding:16px 0;margin:0}.ticket-queue-card :deep(.queue-preview){grid-template-columns:repeat(2,minmax(0,1fr));gap:8px}.ticket-delete-confirm{display:flex;gap:8px;align-items:center;flex-wrap:wrap;font-size:13px;margin-bottom:8px}.ticket-delete-confirm button{min-height:var(--control-height);font-size:12px}.ticket-inline-editor{display:grid;gap:8px;margin-top:8px;padding:12px;border:1px solid var(--line);border-radius:12px;background:var(--page)}.ticket-inline-editor>p{margin:0;font-size:12px}.ticket-inline-editor-actions{display:flex;gap:8px;flex-wrap:wrap}.ticket-inline-editor-actions button{width:auto;min-height:44px}@media(max-width:600px){.ticket-card-heading{flex-wrap:wrap}.ticket-card-actions button{width:44px;min-height:var(--control-height)}.ticket-queue-card :deep(.queue-preview){grid-template-columns:minmax(0,1fr)}.ticket-inline-editor-actions{display:grid;grid-template-columns:1fr 1fr}.ticket-inline-editor-actions button{width:100%}}
</style>

<style scoped>
.ticket-times{display:flex;flex-wrap:wrap;gap:4px 16px;font-size:12px;color:var(--muted);margin:0 0 12px}.ticket-history-label{color:var(--warning)}.ticket-success-result{padding:10px 12px;border-radius:12px;background:var(--success-soft);color:var(--success);font-size:14px;font-weight:600}.ticket-success-result small{display:block;margin-top:4px;font-size:12px;font-weight:400}
.ticket-scope{color:var(--muted);font-size:11px}
.ticket-state{max-width:100%;white-space:normal;overflow-wrap:anywhere}
.ticket-state.is-success{color:var(--success);background:var(--success-soft)}
</style>
