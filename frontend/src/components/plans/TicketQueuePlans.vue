<script setup>
import { computed, ref, watch, onUnmounted } from 'vue';
import AppIcon from '../AppIcon.vue';
import ManualQueuePreview from './ManualQueuePreview.vue';
import { queueEntries } from '../../composables/useManualQueue.js';
const props=defineProps({queues:{type:Array,default:()=>[]},dateFilter:{type:String,default:''},calendarState:Object,courtNames:Array,api:Object,session:Object,busy:Boolean});
const emit=defineEmits(['select','history','changed']);
const deleting=ref(''),mutating=ref(false),error=ref('');
let epoch=0,alive=true;
const visible=computed(()=>props.queues.filter(q=>(q.candidates.length||props.dateFilter)&&(!props.dateFilter||q.target_date===props.dateFilter)).sort((a,b)=>b.target_date.localeCompare(a.target_date)));
const inWindow=q=>(props.calendarState?.queryable_target_dates||[]).includes(q.target_date)&&q.can_open_selection!==false;
function stateLabel(q){if(!q.candidates.length)return '已清空';if(q.plan_status==='expired'||q.target_date<(props.calendarState?.business_date||''))return '已过期';return inWindow(q)?'未执行':'窗口外 · 未执行';}
const valid=generation=>alive&&generation===epoch&&props.session?.status==='authenticated';
watch(()=>[props.session?.status,props.session?.user?.user_id,props.session?.csrfToken,props.session?.invalidationEpoch],()=>{epoch++;deleting.value='';mutating.value=false;error.value='';},{flush:'sync'});
function selectQueue(queue){if(queue.credential_id)emit('select',queue.target_date,queue.credential_id);}
async function remove(q){if(mutating.value||props.busy)return;const generation=epoch;mutating.value=true;error.value='';try{await props.api.removeQueue(q.target_date,q.version,q.credential_id??null);if(valid(generation)){deleting.value='';emit('changed',q.target_date);}}catch(e){if(valid(generation))error.value=e?.status===409?'计划版本已变化，请重新读取后删除。':'删除结果未确认，请重新读取计划核对。';}finally{if(valid(generation))mutating.value=false;}}
onUnmounted(()=>{alive=false;epoch++;});
</script>
<template>
 <section class="ticket-queue-plans" aria-label="人工抢票计划">
  <p v-if="error" class="form-error" role="alert">{{ error }}</p>
  <article v-for="queue in visible" :key="queue.plan_id" class="ticket-queue-card"><header class="ticket-card-heading"><strong>{{ queue.target_date }}</strong><span class="ticket-version">v{{ queue.version }}</span><span class="ticket-state" :class="{'is-expired':stateLabel(queue)==='已过期'}">{{ stateLabel(queue) }}</span><span v-if="!queue.credential_id" class="ticket-scope">历史未关联凭据</span><div class="ticket-card-actions"><button type="button" :disabled="busy||mutating||!queue.credential_id||!inWindow(queue)" :title="!queue.credential_id?'历史计划未关联凭据':inWindow(queue)?'继续到选择预约':'当天不在可查询窗口'" :aria-label="`${queue.target_date}继续选择`" @click="selectQueue(queue)"><AppIcon name="court" /></button><button type="button" :disabled="busy||mutating||!queue.credential_id" :title="queue.credential_id?'在选择预约界面编辑':'历史计划未关联凭据，无法按 Token 编辑'" :aria-label="`编辑${queue.target_date}队列`" @click="selectQueue(queue);deleting='' "><AppIcon name="edit" /></button><button type="button" :disabled="mutating" :aria-label="`${queue.target_date}版本历史`" @click="emit('history',queue.target_date,queue.credential_id??null)"><AppIcon name="clock" /></button><button type="button" :disabled="busy||mutating" :aria-label="`删除${queue.target_date}队列`" @click="deleting=queue.plan_id;error='' "><AppIcon name="trash" /></button></div></header>
   <div v-if="deleting===queue.plan_id" class="ticket-delete-confirm"><span>删除该日计划？历史修订会保留。</span><button type="button" class="danger-button" :disabled="mutating" @click="remove(queue)">确认删除</button><button type="button" class="text-button" :disabled="mutating" @click="deleting=''">取消</button></div>
   <ManualQueuePreview v-if="queue.candidates.length" :entries="queueEntries(queue)" readonly /><p v-else class="ticket-empty">候选已清空，可以查看历史版本。</p>
  </article>
 </section>
</template>
<style scoped>
.ticket-queue-plans{display:grid;gap:10px;min-width:0}.ticket-queue-card{border:1px solid var(--line);border-radius:9px;padding:10px;background:var(--surface)}.ticket-card-heading{display:flex;align-items:center;gap:7px;margin-bottom:9px;min-width:0;font-size:13px}.ticket-version{font-size:11px;color:var(--muted)}.ticket-state{font-size:11px;padding:3px 6px;background:var(--brand-soft);color:var(--brand);border-radius:4px;white-space:nowrap}.ticket-state.is-expired{color:var(--warning);background:var(--warning-soft)}.ticket-card-actions{display:flex;gap:2px;margin-left:auto}.ticket-card-actions button{width:32px;min-height:34px;display:grid;place-items:center;padding:3px;border:0;background:transparent;color:var(--muted);border-radius:5px;cursor:pointer}.ticket-card-actions button:disabled{opacity:.3;cursor:default}.ticket-card-actions button:hover:not(:disabled){background:var(--brand-soft)}.ticket-card-actions .app-icon{width:17px;height:17px}.ticket-empty{font-size:13px;color:var(--muted);padding:12px 0;margin:0}.ticket-queue-card :deep(.queue-preview){grid-template-columns:repeat(2,minmax(0,1fr));gap:10px}.ticket-delete-confirm{display:flex;align-items:center;gap:8px;flex-wrap:wrap;font-size:13px;margin-bottom:8px}.ticket-delete-confirm button{min-height:36px;font-size:12px}@media(max-width:600px){.ticket-card-heading{flex-wrap:wrap}.ticket-card-actions button{width:40px;min-height:44px}.ticket-queue-card :deep(.queue-preview){grid-template-columns:minmax(0,1fr)}}
</style>

<style scoped>
.ticket-scope{color:var(--muted);font-size:11px}
</style>
