<script setup>
import { computed, inject, shallowRef, watch } from 'vue';
import { onBeforeRouteLeave } from 'vue-router';
import AppIcon from '../AppIcon.vue';
import PlanHistory from './PlanHistory.vue';
import ProposalAssistant from './ProposalAssistant.vue';
import LiveAvailabilityPanel from './LiveAvailabilityPanel.vue';
import PlanSectionTabs from './PlanSectionTabs.vue';
import BookingDateStrip from './BookingDateStrip.vue';
import ManualQueueWorkspace from './ManualQueueWorkspace.vue';
import TicketQueuePlans from './TicketQueuePlans.vue';
import ManualQueuePreview from './ManualQueuePreview.vue';
import PlanCredentialControl from './PlanCredentialControl.vue';
import { useManualQueue, queueEntries } from '../../composables/useManualQueue.js';
import { usePlans } from '../../composables/usePlans.js';
const session=inject('sessionStore'),api=inject('planApi'),proposalApi=inject('planningProposalApi',null);
const liveApi=inject('liveAvailabilityApi',null),credentialApi=inject('credentialApi',null);
const courtOptions=shallowRef([]),queryDate=shallowRef(''),selectedCredentialId=shallowRef(''),credentialRefreshKey=shallowRef(0),planDateFilter=shallowRef(''),pendingDeletePlan=shallowRef(null);
const activeSection=shallowRef('query'),manualDate=shallowRef('');
const {plans,defaultWindow,listStatus,metadataError,saving,message,saveError,history,historyPlanId,historyStatus,authorized,refresh,initialize,remove,showHistory,closeHistory}=usePlans(api,session,()=>selectedCredentialId.value);
const visiblePlans=computed(()=>plans.value.filter(plan=>!planDateFilter.value||plan.intent.target_date===planDateFilter.value));
function queueChanged(date){queueState.refreshList();if(date===manualDate.value&&!queueState.dateLocked)queueState.load();}
function selectQueue(date,credentialId=selectedCredentialId.value){if(queueState.dateLocked||!credentialId)return;if(credentialId!==selectedCredentialId.value)selectedCredentialId.value=credentialId;manualDate.value=date;activeSection.value='manual';}
const queueState=useManualQueue(api,session,()=>manualDate.value,()=>selectedCredentialId.value);
const upcomingQueueDate=computed(()=>{
 const lastQuickDate=defaultWindow.value?.queryable_target_dates?.slice(0,3).at(-1);
 if(!lastQuickDate)return '';
 return queueState.queues.filter(queue=>queue.target_date>lastQuickDate&&queue.candidates?.length)
  .map(queue=>queue.target_date).sort()[0]||'';
});
const manualExtraDate=computed(()=>{
 const quickDates=defaultWindow.value?.queryable_target_dates?.slice(0,3)||[];
 return manualDate.value&&!quickDates.includes(manualDate.value)?manualDate.value:upcomingQueueDate.value;
});
onBeforeRouteLeave(async()=>{if(!authorized.value||!queueState.dirty)return true;await queueState.flush();return !queueState.dirty;});
watch(defaultWindow,value=>{
 if(!value){manualDate.value='';queryDate.value='';activeSection.value='query';}
 else {if(!queryDate.value)queryDate.value=value.queryable_target_dates?.[2]||value.default_target_date||'';if(!manualDate.value)manualDate.value=value.default_target_date||value.queryable_target_dates?.[2]||'';}
},{flush:'sync',immediate:true});
function rememberCourtLabels(names){if(JSON.stringify(courtOptions.value)!==JSON.stringify(names))courtOptions.value=[...names];}
watch(()=>[session?.status,session?.user?.user_id,session?.invalidationEpoch],()=>{courtOptions.value=[];pendingDeletePlan.value=null;planDateFilter.value='';},{flush:'sync'});
const queryContextKey=computed(()=>JSON.stringify({user:session?.user?.user_id,epoch:session?.invalidationEpoch}));
</script>
<template>
 <div class="plans-page">
  <h1 class="sr-only">预约计划</h1>
  <div v-if="!authorized" class="panel"><p role="alert">{{ session?.status==='unauthenticated' ? '登录状态已失效，请重新登录。' : '暂时无法确认登录状态，请重试。' }}</p></div>
  <template v-else>
   <PlanSectionTabs v-model="activeSection" :plan-count="plans.length+queueState.queues.filter(q=>q.candidates.length).length" />
   <p v-if="metadataError" class="form-error" role="alert">日期范围读取失败，请重试。 <button class="secondary-button" type="button" @click="initialize">重新读取</button></p>
   <p v-if="message" class="form-success" role="status">{{ message }}</p>
   <p v-if="saveError" class="form-error" role="alert">{{ saveError }}</p>
   <section v-show="activeSection==='query'" id="plan-panel-query" role="tabpanel" aria-labelledby="plan-tab-query" class="plan-workspace-section query-workspace">
    <LiveAvailabilityPanel v-if="liveApi && credentialApi" v-model:credential-id="selectedCredentialId" :credential-refresh-key="credentialRefreshKey" :api="liveApi" :credential-api="credentialApi" :session="session" :calendar-state="defaultWindow" :target-date="queryDate" :context-key="queryContextKey" @date-change="queryDate=$event" @court-labels="rememberCourtLabels" />
    <BookingDateStrip v-else v-model="queryDate" :state="defaultWindow" />
   </section>
   <section v-show="activeSection==='manual'" id="plan-panel-manual" role="tabpanel" aria-labelledby="plan-tab-manual" class="plan-workspace-section">
    <div class="selection-toolbar"><BookingDateStrip v-model="manualDate" :state="defaultWindow" :extra-date="manualExtraDate" :busy="saving||queueState.dateLocked" @refresh="queueState.load"><template #actions><PlanCredentialControl v-if="credentialApi&&activeSection==='manual'" v-model="selectedCredentialId" :api="credentialApi" :session="session" :timezone-name="defaultWindow?.business_timezone_name||'Asia/Shanghai'" :disabled="queueState.dateLocked" @updated="credentialRefreshKey++" /></template></BookingDateStrip></div>
    <ManualQueueWorkspace :state="queueState" :court-names="courtOptions" :target-date="manualDate" />
   </section>
   <section v-show="activeSection==='agent'" id="plan-panel-agent" role="tabpanel" aria-labelledby="plan-tab-agent" class="plan-workspace-section">
    <div v-if="credentialApi" class="agent-scope-bar"><span>当前预约凭据</span><PlanCredentialControl v-if="activeSection==='agent'" v-model="selectedCredentialId" :api="credentialApi" :session="session" :timezone-name="defaultWindow?.business_timezone_name||'Asia/Shanghai'" :disabled="queueState.dateLocked" @updated="credentialRefreshKey++" /></div>
    <p v-if="proposalApi&&!selectedCredentialId" class="muted agent-scope-note">先选择预约凭据，再保存 Agent 生成的计划。</p>
    <ProposalAssistant v-if="proposalApi" :plans="plans" :plan-api="api" :proposal-api="proposalApi" :session="session" :credential-id="selectedCredentialId" @refresh-request="refresh" />
    <p v-else class="panel muted">Agent 服务当前未配置，请先检查模型设置。</p>
   </section>
   <section v-show="activeSection==='current'" id="plan-panel-current" role="tabpanel" aria-labelledby="plan-tab-current" class="plan-workspace-section">
   <div class="ticket-filter-bar">
    <div v-if="credentialApi" class="ticket-filter-credential"><PlanCredentialControl v-model="selectedCredentialId" :api="credentialApi" :session="session" :timezone-name="defaultWindow?.business_timezone_name||'Asia/Shanghai'" :disabled="queueState.dateLocked" @updated="credentialRefreshKey++" /></div>
    <label class="ticket-filter-date"><AppIcon name="calendar" /><input v-model="planDateFilter" type="date" aria-label="抢票计划日期" /></label>
    <button type="button" class="text-button ticket-filter-all" @click="planDateFilter=''">全部日期</button>
    <div class="ticket-filter-meta"><span class="ticket-filter-count">{{ visiblePlans.length+queueState.queues.filter(q=>(q.candidates.length||planDateFilter)&&(!planDateFilter||q.target_date===planDateFilter)).length }} 份计划</span><button type="button" class="text-button" :disabled="saving||queueState.dateLocked" aria-label="重新读取抢票计划" @click="refresh();queueState.refreshList()"><AppIcon name="refresh" /></button></div>
   </div>

   <section v-if="plans.length||listStatus==='loading'||listStatus==='error'" class="panel" aria-labelledby="plans-list-title"><div class="plan-section-heading"><h2 id="plans-list-title">Agent 意向</h2><button data-testid="refresh-plans" class="secondary-button" type="button" :disabled="saving || listStatus==='loading'" @click="refresh();queueState.refreshList()" aria-label="刷新计划" title="刷新计划"><AppIcon name="refresh" /></button></div>
    <p v-if="listStatus==='loading'" class="muted" role="status">正在读取计划…</p>
    <p v-else-if="listStatus==='error'" class="form-error" role="alert">计划读取失败，请检查网络后刷新重试。</p>
    <div v-else class="plan-list"><article v-for="plan in visiblePlans" :key="plan.plan_id" class="plan-card"><div><span class="plan-draft-tag">{{ !plan.credential_id?'历史未关联凭据':plan.intent.target_date<(defaultWindow?.business_date||'')?'已过期 · 未执行':(defaultWindow?.queryable_target_dates||[]).includes(plan.intent.target_date)?'未执行 · 当前凭据':'窗口外 · 未执行' }}</span><h3>{{ plan.intent.venue_preference }}</h3><p>{{ plan.intent.target_date }} · {{ plan.intent.preferred_start_times.join(' → ') }} · {{ plan.intent.duration_minutes }} 分钟</p><p class="muted">版本 {{ plan.version }} · {{ plan.intent.court_preferences.join(' → ') || '场地未指定' }}</p></div><div class="plan-actions"><button data-testid="history-plan" class="text-button" type="button" :disabled="saving" @click="showHistory(plan.plan_id)">版本历史</button><button class="text-button" type="button" :disabled="saving" :aria-label="`删除计划${plan.intent.venue_preference}`" @click="pendingDeletePlan=plan">删除</button></div></article></div>
   <div v-if="pendingDeletePlan" class="ticket-delete-plan"><span>删除“{{ pendingDeletePlan.intent.venue_preference }}”？历史会保留。</span><button type="button" class="danger-button" :disabled="saving" @click="remove(pendingDeletePlan);pendingDeletePlan=null">确认删除</button><button type="button" class="text-button" @click="pendingDeletePlan=null">取消</button></div>
   </section>
   <TicketQueuePlans :queues="queueState.queues" :date-filter="planDateFilter" :calendar-state="defaultWindow" :court-names="courtOptions" :api="api" :session="session" :busy="queueState.dateLocked" @changed="queueChanged" @select="selectQueue" @history="queueState.showHistory" />
   <section v-if="queueState.history" class="panel queue-history"><div class="plan-section-heading"><h2>队列版本历史</h2><button type="button" class="text-button" @click="queueState.history=null">关闭历史</button></div><details v-for="revision in queueState.history" :key="revision.revision_id"><summary>版本 {{ revision.revision_number }} · {{ revision.target_date }}{{ revision.deleted?' · 已删除':'' }}</summary><ManualQueuePreview :entries="queueEntries(revision)" readonly /></details></section><p v-if="queueState.historyError" class="form-error" role="alert">{{ queueState.historyError }}</p>
   <PlanHistory v-if="historyPlanId" :revisions="history" :status="historyStatus" @close="closeHistory" @retry="showHistory(historyPlanId)" />
   </section>
  </template>
 </div>
</template>
<style>
.plans-page{min-width:0}.plans-page>.panel,.plan-edit-section{margin-bottom:22px}.plan-notice{padding:16px 20px;border-radius:12px;border:1px solid var(--line);background:var(--brand-soft);color:var(--brand-dark);margin:0 0 24px;line-height:1.7}.plan-section-heading{display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap}.plan-section-heading>div{min-width:0}.plan-list{display:grid;margin-top:18px}.plan-card{display:flex;align-items:center;justify-content:space-between;gap:20px;border-top:1px solid var(--line);padding:22px 0;min-width:0}.plan-card>div{min-width:0}.plan-card h3{margin:8px 0;overflow-wrap:anywhere}.plan-card p{margin:6px 0;overflow-wrap:anywhere}.plan-draft-tag{display:inline-block;color:var(--brand-dark);background:var(--brand-soft);padding:4px 10px;font-size:13px;border-radius:6px}.plan-actions{display:flex;flex-wrap:wrap;gap:10px;flex-shrink:0}.plan-empty{padding:24px 0;color:var(--muted)}.plan-feedback{border:1px solid var(--danger);background:var(--danger-soft);border-radius:12px;padding:18px;margin:0 0 20px;line-height:1.7}.plan-feedback button{margin:4px 8px 4px 0}.plan-feedback p{margin:0 0 10px}.plan-conflict{background:var(--warning-soft);border-color:var(--warning);color:var(--warning)}@media(max-width:700px){.plan-card{flex-direction:column;align-items:stretch}.plan-actions{flex-shrink:1}.plans-page .panel{padding:20px}}
</style>

<style scoped>
.agent-scope-bar{display:flex;align-items:center;justify-content:space-between;gap:10px;padding:8px 12px;margin-bottom:10px;border:1px solid var(--line);border-radius:8px;background:var(--surface);font-size:13px;color:var(--muted)}.agent-scope-note{margin:0 0 10px;padding:8px 12px}@media(max-width:600px){.agent-scope-bar{flex-wrap:wrap}}
</style>
<style scoped>
.plans-heading{display:flex;align-items:center;justify-content:space-between;gap:12px;margin-bottom:12px}.plans-heading h1{font-size:26px;margin:0;letter-spacing:-.03em}.plans-heading-actions{display:flex;align-items:center;gap:12px}.intent-badge{font-size:12px;color:var(--muted)}.plans-heading button,.manual-start button{display:inline-flex;align-items:center;gap:6px;min-height:44px}.plan-workspace-section{min-width:0}.manual-layout{display:grid;gap:16px;align-items:start}.manual-layout.is-editing{grid-template-columns:minmax(0,1fr) 400px}.manual-observation{min-width:0;border:1px solid var(--line);border-radius:12px;background:var(--surface);overflow:clip}.manual-observation :deep(.live-availability-panel){border:0;border-radius:0;margin:0;box-shadow:none;padding:16px 20px}.manual-start{display:flex;justify-content:space-between;align-items:center;gap:12px;border-top:1px solid var(--line);padding:12px 20px;font-size:13px}.plan-edit-section{min-width:0;margin:0}.plan-edit-section :deep(.plan-editor){padding:20px}.window-details{font-size:13px;color:var(--muted);margin-top:8px}.window-details>summary{cursor:pointer;min-height:44px;display:flex;align-items:center;gap:6px}.plan-reference-details{margin:8px 0 16px;color:var(--muted);font-size:13px}.plan-reference-details>summary{display:flex;align-items:center;gap:6px;cursor:pointer;min-height:44px;width:fit-content}.plan-reference-details[open]>summary{margin-bottom:8px}.plan-reference-details :deep(.venue-catalog-status){margin-bottom:0}.plan-section-heading h2{font-size:18px;margin:0}.plan-card{padding:16px 0}.plan-section-heading button{min-width:44px;min-height:44px;display:grid;place-items:center}.plan-reference-details :deep(.availability-simulation){margin-top:0}.plan-reference-details :deep(.simulation-notice){padding:8px 12px;font-size:13px}.plan-draft-tag{font-size:12px;padding:2px 7px}.plan-card h3{font-size:17px}.plan-card p{font-size:14px}.plans-page>.panel{margin-bottom:16px}.plans-page>.form-success{padding:0;background:transparent;border:0;font-size:13px;margin:0 0 12px;color:var(--brand)}@media(max-width:1100px){.manual-layout.is-editing{grid-template-columns:minmax(0,1fr)}.plan-edit-section{max-width:none}}@media(max-width:600px){.plans-heading h1{font-size:23px}.intent-badge{display:none}.manual-observation :deep(.live-availability-panel){padding:12px}.manual-start{padding:12px}.plan-edit-section :deep(.plan-editor){padding:16px}}

.selection-toolbar{display:flex;align-items:center;gap:8px;background:var(--surface);border:1px solid var(--line);border-radius:10px;margin-bottom:12px;padding-right:12px}.selection-toolbar>.booking-date-strip{flex:1;border:0;padding:10px 12px}.selection-toolbar>button{display:flex;align-items:center;gap:5px;white-space:nowrap;min-height:40px}.selection-empty{padding:48px 20px;text-align:center;border:1px dashed var(--line);border-radius:10px;color:var(--muted)}.selection-empty>.app-icon{width:30px;height:30px}.query-workspace{min-width:0}.plan-edit-section{max-width:100%}.plan-edit-section :deep(.plan-fieldset){grid-template-columns:repeat(2,minmax(0,1fr))}.plan-edit-section :deep(.plan-fieldset>.plan-two-columns){grid-column:1/-1}.plan-edit-section :deep(.plan-fieldset>#plan-preferred_start_times){grid-column:1/-1}.plan-edit-section :deep(.plan-fieldset>.grid-apply-confirmation),.plan-edit-section :deep(.plan-fieldset>.editor-disclosure){grid-column:1/-1}.plan-section-heading>button[data-testid=new-current-plan]{margin-left:auto;display:flex;gap:5px;font-size:13px}.plan-section-heading{flex-wrap:nowrap}@media(max-width:650px){.selection-toolbar{flex-wrap:wrap;padding:8px}.selection-toolbar>.booking-date-strip{flex-basis:100%;padding:0}.selection-toolbar>button{margin-left:auto}.plan-edit-section :deep(.plan-fieldset){grid-template-columns:minmax(0,1fr)}}
</style>

<style scoped>
.current-queues{margin-top:12px}.current-queues h2,.queue-history h2{font-size:18px}.current-queues article{padding:12px 0;border-top:1px solid var(--line)}.current-queues article :deep(.queue-preview){grid-template-columns:repeat(2,minmax(0,1fr))}.current-queues h3{font-size:14px}.queue-history details>summary{min-height:44px;display:flex;align-items:center;cursor:pointer}.queue-history :deep(.queue-preview){margin:10px 0}@media(max-width:600px){.current-queues article :deep(.queue-preview){grid-template-columns:minmax(0,1fr)}}
</style>

<style scoped>
.ticket-filter-bar{display:grid;grid-template-columns:minmax(0,240px) minmax(155px,190px) max-content minmax(90px,1fr);gap:8px;align-items:center;padding:8px 12px;border:1px solid var(--line);border-radius:8px;background:var(--surface);margin-bottom:10px;min-width:0}.ticket-filter-credential,.ticket-filter-date{min-width:0}.ticket-filter-bar :deep(.plan-credential-control){max-width:100%;min-width:0}.ticket-filter-date{display:flex;align-items:center;gap:6px;min-width:0;color:var(--muted)}.ticket-filter-bar input{min-height:36px;width:100%;min-width:0;padding:5px 8px;border:1px solid var(--line);border-radius:5px;color:var(--ink);background:var(--surface);font:inherit;font-size:13px}.ticket-filter-bar .ticket-filter-all,.ticket-filter-meta button{min-height:36px;font-size:12px;padding:4px 8px;white-space:nowrap}.ticket-filter-meta{display:flex;align-items:center;justify-content:flex-end;gap:6px;min-width:0}.ticket-filter-count{font-size:12px;color:var(--muted);white-space:nowrap}.ticket-delete-plan{display:flex;gap:8px;align-items:center;flex-wrap:wrap;font-size:13px}.plan-card{padding:10px 0}.plan-card h3{font-size:15px;margin:4px 0}.plan-card p{font-size:12px}.plan-actions button{min-height:36px;padding:5px 8px;font-size:12px}@media(max-width:800px){.ticket-filter-bar{grid-template-columns:minmax(0,1fr) minmax(150px,1fr)}.ticket-filter-meta{grid-column:1/-1;justify-content:flex-end}.ticket-filter-bar input{min-height:40px}}@media(max-width:460px){.ticket-filter-bar{padding:8px;gap:6px}.ticket-filter-credential,.ticket-filter-meta{grid-column:1/-1}.ticket-filter-bar input,.ticket-filter-bar .ticket-filter-all,.ticket-filter-meta button{min-height:44px}}
</style>
