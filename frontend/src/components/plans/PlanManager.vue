<script setup>
import { computed, inject, onBeforeUnmount, shallowRef, watch } from 'vue';
import { onBeforeRouteLeave, useRoute, useRouter } from 'vue-router';
import AppIcon from '../AppIcon.vue';
import PlanHistory from './PlanHistory.vue';
import ProposalModeWorkspace from './ProposalModeWorkspace.vue';
import LiveAvailabilityPanel from './LiveAvailabilityPanel.vue';
import PlanSectionTabs from './PlanSectionTabs.vue';
import BookingDateStrip from './BookingDateStrip.vue';
import ManualQueueWorkspace from './ManualQueueWorkspace.vue';
import QueuePlanDashboard from './QueuePlanDashboard.vue';
import ManualQueuePreview from './ManualQueuePreview.vue';
import PlanCredentialControl from './PlanCredentialControl.vue';
import BookingExecutionSettings from '../BookingExecutionSettings.vue';
import EmailNotificationSettings from '../EmailNotificationSettings.vue';
import OrderQueryPanel from './OrderQueryPanel.vue';
import { useManualQueue, queueEntries } from '../../composables/useManualQueue.js';
import { usePlans } from '../../composables/usePlans.js';
import { visibleIntentPlans, visibleManualQueuePlans } from '../../utils/planQueueVisibility.js';
import { agentModelKey, agentModelWasRecentlyReady, clearAgentModelReady, rememberAgentModelReady } from '../../utils/agentReadiness.js';
import { providerErrorMessage } from '../../api/providerErrors.js';
const session=inject('sessionStore'),api=inject('planApi'),proposalApi=inject('planningProposalApi',null),intentProposalApi=inject('intentPlanningProposalApi',null);
const liveApi=inject('liveAvailabilityApi',null),credentialApi=inject('credentialApi',null);
const aiModelsApi=inject('aiModelsApi',null),router=useRouter(),route=useRoute();
const orderApi=inject('orderApi',null);
const courtOptions=shallowRef([]),queueScopeLabel=shallowRef(''),queryDate=shallowRef(''),selectedCredentialId=shallowRef(''),credentialRefreshKey=shallowRef(0),planDateFilter=shallowRef(''),pendingDeletePlan=shallowRef(null);
const activeSection=shallowRef(['query','manual','agent','current','orders'].includes(route.query.tab)?route.query.tab:'query'),manualDate=shallowRef('');
const overviewCounts=shallowRef(null),overviewRefreshKey=shallowRef(0);
const agentReadiness=shallowRef('idle');
const agentReadinessError=shallowRef('');
const currentVisited=shallowRef(activeSection.value==='current'),executionSettingsOpen=shallowRef(false);
const leaving=shallowRef(0);
let agentCheckSequence=0;
const {plans,catalog,defaultWindow,listStatus,metadataError,saving,message,saveError,history,historyPlanId,historyStatus,historyBefore,loadMoreHistory,authorized,refresh,initialize,remove,showHistory,closeHistory}=usePlans(api,session,()=>selectedCredentialId.value,{requireCredential:true});
watch(catalog,value=>{if(Array.isArray(value?.manual_queue_court_labels))courtOptions.value=[...value.manual_queue_court_labels];},{immediate:true});
const visiblePlans=computed(()=>visibleIntentPlans(plans.value,{dateFilter:planDateFilter.value,businessDate:defaultWindow.value?.business_date||''}));
function queueChanged(date){overviewRefreshKey.value++;queueState.refreshList();if(date===manualDate.value&&!queueState.dateLocked)queueState.load();}
function selectQueue(date,credentialId=selectedCredentialId.value){if(queueState.dateLocked||!credentialId)return;if(credentialId!==selectedCredentialId.value)selectedCredentialId.value=credentialId;manualDate.value=date;activeSection.value='manual';}
const queueState=useManualQueue(api,session,()=>manualDate.value,()=>selectedCredentialId.value,()=>activeSection.value==='manual');
const visibleQueuePlans=computed(()=>visibleManualQueuePlans(queueState.queues,{dateFilter:planDateFilter.value,businessDate:defaultWindow.value?.business_date||''}));
const planCount=computed(()=>visiblePlans.value.length+(overviewCounts.value?.all??visibleQueuePlans.value.filter(queue=>queue.candidates?.length).length));
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
onBeforeRouteLeave(async()=>{if(!authorized.value||!queueState.dirty)return true;leaving.value++;try{await queueState.flush();return !queueState.dirty;}finally{leaving.value--;}});
watch(defaultWindow,value=>{
 if(!value){manualDate.value='';queryDate.value='';}
 else {if(!queryDate.value)queryDate.value=value.queryable_target_dates?.[2]||value.default_target_date||'';if(!manualDate.value)manualDate.value=value.default_target_date||value.queryable_target_dates?.[2]||'';}
},{flush:'sync',immediate:true});
function onAgentSaved({target_date}={}){queueChanged(target_date);}
function openManualFromAgent({target_date}={}){
 if(queueState.dateLocked)return;
 if(typeof target_date==='string'&&/^\d{4}-\d{2}-\d{2}$/.test(target_date))manualDate.value=target_date;
 activeSection.value='manual';
}
function rememberCourtLabels(names){const labels=catalog.value?.manual_queue_court_labels||names;if(JSON.stringify(courtOptions.value)!==JSON.stringify(labels))courtOptions.value=[...labels];}
function rememberQueueScope(label){queueScopeLabel.value=typeof label==='string'?label:'';}
function redirectToModelSettings(reason){
 clearAgentModelReady();
 if(session?.status!=='authenticated')return router.replace({name:'login'});
 return router.replace({name:'ai-models',query:{returnTo:'agent',reason}});
}
async function checkAgentService(){
 if(agentReadiness.value==='checking'||agentReadiness.value==='ready')return;
 const sequence=++agentCheckSequence;
 const userId=session?.user?.user_id;
 agentReadiness.value='checking';
 if(!aiModelsApi){agentReadiness.value='blocked';await redirectToModelSettings('provider_not_configured');return;}
 try{
  const state=await aiModelsApi.list();
  if(sequence!==agentCheckSequence||session?.user?.user_id!==userId)return;
  if(activeSection.value!=='agent'){agentReadiness.value='idle';return;}
  const modelId=state?.effective_model_id;
  const model=modelId==='service_default'
   ? state?.service_default
   : state?.models?.find(item=>item.id===modelId);
  if(!modelId||!model){agentReadiness.value='blocked';await redirectToModelSettings('provider_not_configured');return;}
  if(model.auth_mode==='bearer'&&model.has_api_key!==true){agentReadiness.value='blocked';await redirectToModelSettings('provider_api_key_required');return;}
  const modelKey=agentModelKey({...model,id:modelId},session);
  if(!agentModelWasRecentlyReady(userId,modelKey))await aiModelsApi.test(modelId);
  if(sequence!==agentCheckSequence||session?.user?.user_id!==userId)return;
  rememberAgentModelReady(userId,modelKey);
  if(activeSection.value!=='agent'){agentReadiness.value='idle';return;}
  agentReadinessError.value='';
  agentReadiness.value='ready';
 }catch(error){
  if(sequence!==agentCheckSequence)return;
  if(activeSection.value!=='agent'){agentReadiness.value='idle';return;}
  if(error?.sessionInvalid||session?.status==='unauthenticated'){agentReadiness.value='blocked';await router.replace({name:'login'});return;}
  if(['provider_rate_limited','ai_call_rate_limited','ai_call_in_progress','ai_service_busy'].includes(error?.code)){
   agentReadiness.value='error';agentReadinessError.value=providerErrorMessage(error.code);return;
  }
  agentReadiness.value='blocked';
  agentReadinessError.value='';
  await redirectToModelSettings(typeof error?.code==='string'?error.code:'provider_unavailable');
 }
}
async function changeSection(section){
 if(section==='orders'||route.query.tab==='orders'){
  const failure=await router.replace({query:{...route.query,tab:section}});
  if(failure||route.name!=='plans')return;
 }
 activeSection.value=section;
 if(section==='current')currentVisited.value=true;
 if(section==='agent'){agentReadinessError.value='';void checkAgentService();}
 else if(!['ready','checking'].includes(agentReadiness.value)){agentCheckSequence++;agentReadiness.value='idle';agentReadinessError.value='';}
}
watch(()=>route.query.tab,(value,previous)=>{
 if(value==='orders'||previous==='orders'){
  const section=['query','manual','agent','current','orders'].includes(value)?value:'query';
  activeSection.value=section;
  if(section==='agent')void checkAgentService();
  else if(!['ready','checking'].includes(agentReadiness.value)){agentCheckSequence++;agentReadiness.value='idle';}
 }
});
watch(()=>[session?.status,session?.user?.user_id,session?.csrfToken,session?.invalidationEpoch],()=>{agentCheckSequence++;agentReadiness.value='idle';currentVisited.value=activeSection.value==='current';executionSettingsOpen.value=false;courtOptions.value=[];queueScopeLabel.value='';pendingDeletePlan.value=null;planDateFilter.value='';overviewCounts.value=null;},{flush:'sync'});
onBeforeUnmount(()=>{agentCheckSequence++;});
const queryContextKey=computed(()=>JSON.stringify({user:session?.user?.user_id,epoch:session?.invalidationEpoch}));
if(activeSection.value==='agent')void checkAgentService();
</script>
<template>
 <div class="plans-page">
  <h1 class="sr-only">预约计划</h1>
  <div v-if="!authorized" class="panel"><p role="alert">{{ session?.status==='unauthenticated' ? '登录状态已失效，请重新登录。' : '暂时无法确认登录状态，请重试。' }}</p></div>
  <template v-else>
   <PlanSectionTabs :model-value="activeSection" :plan-count="planCount" @update:model-value="changeSection" />
   <p v-if="leaving" class="status-loading" role="status">正在保存队列，完成后切换页面…</p>
   <p v-if="metadataError" class="form-error" role="alert">日期范围读取失败，请重试。 <button class="secondary-button" type="button" @click="initialize">重新读取</button></p>
   <p v-if="message" class="form-success" role="status">{{ message }}</p>
   <p v-if="saveError" class="form-error" role="alert">{{ saveError }}</p>
   <section v-show="activeSection==='query'" id="plan-panel-query" role="tabpanel" aria-labelledby="plan-tab-query" class="plan-workspace-section query-workspace">
    <LiveAvailabilityPanel v-if="liveApi && credentialApi" :active="activeSection==='query'" v-model:credential-id="selectedCredentialId" :credential-refresh-key="credentialRefreshKey" :api="liveApi" :credential-api="credentialApi" :session="session" :calendar-state="defaultWindow" :target-date="queryDate" :context-key="queryContextKey" @date-change="queryDate=$event" @court-labels="rememberCourtLabels" @queue-scope="rememberQueueScope" />
    <BookingDateStrip v-else v-model="queryDate" :state="defaultWindow" />
   </section>
   <section v-show="activeSection==='manual'" id="plan-panel-manual" role="tabpanel" aria-labelledby="plan-tab-manual" class="plan-workspace-section">
    <div class="manual-plan-card">
    <div class="selection-toolbar"><BookingDateStrip v-model="manualDate" :state="defaultWindow" :extra-date="manualExtraDate" :busy="saving||queueState.dateLocked" @refresh="queueState.load"><template #actions><PlanCredentialControl v-if="credentialApi&&activeSection==='manual'" v-model="selectedCredentialId" :api="credentialApi" :session="session" :timezone-name="defaultWindow?.business_timezone_name||'Asia/Shanghai'" :disabled="queueState.dateLocked" @updated="credentialRefreshKey++" /></template></BookingDateStrip></div>
    <ManualQueueWorkspace :state="queueState" :court-names="courtOptions" :scope-label="queueScopeLabel" :target-date="manualDate" />
    </div>
   </section>
   <section v-show="activeSection==='agent'" id="plan-panel-agent" role="tabpanel" aria-labelledby="plan-tab-agent" class="plan-workspace-section">
    <p v-if="agentReadiness==='checking'" class="panel status-loading" role="status">正在检查模型配置和连接状态…</p>
    <ProposalModeWorkspace v-else-if="agentReadiness==='ready'&&proposalApi" :plans="plans" :plan-api="api" :proposal-api="proposalApi" :intent-proposal-api="intentProposalApi" :credential-api="credentialApi" :credential-refresh-key="credentialRefreshKey" :session="session" :credential-id="selectedCredentialId" :scope-label="queueScopeLabel" @refresh-request="refresh" @saved="onAgentSaved" @manual-request="openManualFromAgent" @provider-unavailable="redirectToModelSettings">
     <template #header-actions>
      <PlanCredentialControl v-if="credentialApi" v-model="selectedCredentialId" :api="credentialApi" :session="session" :timezone-name="defaultWindow?.business_timezone_name||'Asia/Shanghai'" :disabled="queueState.dateLocked" @updated="credentialRefreshKey++" />
     </template>
    </ProposalModeWorkspace>
    <p v-else-if="agentReadiness==='error'" class="panel form-error" role="alert">{{ agentReadinessError }} <button class="secondary-button" type="button" @click="checkAgentService">重新检查</button></p>
    <p v-else-if="agentReadiness==='blocked'" class="panel muted">正在前往模型设置；请检查模型配置并测试连接。</p>
    <p v-else class="panel muted">选择 Agent 预约后会先检查模型配置。</p>
   </section>
   <section v-show="activeSection==='current'" id="plan-panel-current" role="tabpanel" aria-labelledby="plan-tab-current" class="plan-workspace-section">
   <QueuePlanDashboard v-if="currentVisited" v-model:date-filter="planDateFilter" :api="api" :session="session" :credential-id="selectedCredentialId" :calendar-state="defaultWindow" :active="activeSection==='current'" :busy="queueState.dateLocked" :refresh-key="overviewRefreshKey" @select="selectQueue" @history="queueState.showHistory" @changed="queueChanged" @count-change="overviewCounts=$event">
    <template #credentials><PlanCredentialControl v-if="credentialApi" v-model="selectedCredentialId" :api="credentialApi" :session="session" :timezone-name="defaultWindow?.business_timezone_name||'Asia/Shanghai'" :disabled="queueState.dateLocked" @updated="credentialRefreshKey++" /></template>
    <template #empty-action><button type="button" class="text-button" @click="changeSection('manual')">选择预约</button></template>
   </QueuePlanDashboard>

   <section v-if="visiblePlans.length||listStatus==='loading'||listStatus==='error'" class="panel" aria-labelledby="plans-list-title"><div class="plan-section-heading"><h2 id="plans-list-title">Agent 意向</h2><button data-testid="refresh-plans" class="secondary-button" type="button" :disabled="saving || listStatus==='loading'" @click="refresh();queueState.refreshList()" aria-label="刷新计划" title="刷新计划"><AppIcon name="refresh" /></button></div>
    <p v-if="listStatus==='loading'" class="muted" role="status">正在读取计划…</p>
    <p v-else-if="listStatus==='error'" class="form-error" role="alert">计划读取失败，请检查网络后刷新重试。</p>
    <div v-else class="plan-list"><article v-for="plan in visiblePlans" :key="plan.plan_id" class="plan-card"><div><span class="plan-draft-tag">{{ !plan.credential_id?'历史未关联凭据':plan.intent.target_date<(defaultWindow?.business_date||'')?'已过期 · 未执行':(defaultWindow?.queryable_target_dates||[]).includes(plan.intent.target_date)?'未执行 · 当前凭据':'窗口外 · 未执行' }}</span><h3>{{ plan.intent.venue_preference }}</h3><p>{{ plan.intent.target_date }} · {{ plan.intent.preferred_start_times.join(' → ') }} · {{ plan.intent.duration_minutes }} 分钟</p><p class="muted">版本 {{ plan.version }} · {{ plan.intent.court_preferences.join(' → ') || '场地未指定' }}</p></div><div class="plan-actions"><button data-testid="history-plan" class="text-button" type="button" :disabled="saving" @click="showHistory(plan.plan_id)">版本历史</button><button class="text-button" type="button" :disabled="saving" :aria-label="`删除计划${plan.intent.venue_preference}`" @click="pendingDeletePlan=plan">删除</button></div></article></div>
   <div v-if="pendingDeletePlan" class="ticket-delete-plan"><span>删除“{{ pendingDeletePlan.intent.venue_preference }}”？历史会保留。</span><button type="button" class="danger-button" :disabled="saving" @click="remove(pendingDeletePlan);pendingDeletePlan=null">确认删除</button><button type="button" class="text-button" @click="pendingDeletePlan=null">取消</button></div>
   </section>
   <details v-if="credentialApi" class="disclosure-panel execution-settings-disclosure" :open="executionSettingsOpen" @toggle="executionSettingsOpen=$event.target.open"><summary>执行设置<small>复核、校时、付款延迟和邮件通知</small></summary><div class="disclosure-body"><BookingExecutionSettings v-if="executionSettingsOpen" :api="credentialApi" /><EmailNotificationSettings v-if="executionSettingsOpen" :api="credentialApi" :session="session" /></div></details>

   <section v-if="queueState.history" class="panel queue-history"><div class="plan-section-heading"><h2>队列版本历史</h2><button type="button" class="text-button" @click="queueState.closeHistory">关闭历史</button></div><details v-for="revision in queueState.history" :key="revision.revision_id"><summary>版本 {{ revision.revision_number }} · {{ revision.target_date }}{{ revision.deleted?' · 已删除':'' }}</summary><ManualQueuePreview :entries="queueEntries(revision)" readonly /></details><button v-if="queueState.historyCursor" type="button" class="secondary-button" :disabled="queueState.historyLoading" @click="queueState.loadMoreHistory">加载更早版本</button></section><p v-if="queueState.historyError" class="form-error" role="alert">{{ queueState.historyError }}</p>
   <PlanHistory v-if="historyPlanId" :revisions="history" :status="historyStatus" :has-more="Boolean(historyBefore)" @more="loadMoreHistory" @close="closeHistory" @retry="showHistory(historyPlanId)" />
   </section>
   <section v-show="activeSection==='orders'" id="plan-panel-orders" role="tabpanel" aria-labelledby="plan-tab-orders" class="plan-workspace-section">
    <OrderQueryPanel v-if="activeSection==='orders'&&orderApi" :api="orderApi" :session="session" :credential-id="selectedCredentialId" :refresh-key="credentialRefreshKey">
     <template #credentials><PlanCredentialControl v-if="credentialApi" v-model="selectedCredentialId" :api="credentialApi" :session="session" :timezone-name="defaultWindow?.business_timezone_name||'Asia/Shanghai'" :disabled="queueState.dateLocked" @updated="credentialRefreshKey++" /></template>
    </OrderQueryPanel>
    <p v-else-if="activeSection==='orders'" class="panel form-error" role="alert">订单查询暂时不可用，请刷新页面重试。</p>
   </section>
  </template>
 </div>
</template>
<style>
.plans-page{min-width:0}.plans-page>.panel,.plan-edit-section{margin-bottom:24px}.plan-notice{padding:16px 16px;border-radius:16px;border:1px solid var(--line);background:var(--brand-soft);color:var(--brand-dark);margin:0 0 24px;line-height:1.7}.plan-section-heading{display:flex;align-items:center;justify-content:space-between;gap:16px;flex-wrap:wrap}.plan-section-heading>div{min-width:0}.plan-list{display:grid;margin-top:16px}.plan-card{display:flex;align-items:center;justify-content:space-between;gap:16px;border-top:1px solid var(--line);padding:24px 0;min-width:0}.plan-card>div{min-width:0}.plan-card h3{margin:8px 0;overflow-wrap:anywhere}.plan-card p{margin:8px 0;overflow-wrap:anywhere}.plan-draft-tag{display:inline-block;color:var(--brand-dark);background:var(--brand-soft);padding:8px 8px;font-size:13px;border-radius:8px}.plan-actions{display:flex;flex-wrap:wrap;gap:8px;flex-shrink:0}.plan-empty{padding:24px 0;color:var(--muted)}.plan-feedback{border:1px solid var(--danger);background:var(--danger-soft);border-radius:16px;padding:16px;margin:0 0 16px;line-height:1.7}.plan-feedback button{margin:8px 8px 8px 0}.plan-feedback p{margin:0 0 8px}.plan-conflict{background:var(--warning-soft);border-color:var(--warning);color:var(--warning)}@media(max-width:700px){.plan-card{flex-direction:column;align-items:stretch}.plan-actions{flex-shrink:1}.plans-page .panel{padding:16px}}
</style>

<style scoped>
.plans-heading{display:flex;align-items:center;justify-content:space-between;gap:16px;margin-bottom:16px}.plans-heading h1{font-size:26px;margin:0;letter-spacing:-.03em}.plans-heading-actions{display:flex;align-items:center;gap:16px}.intent-badge{font-size:12px;color:var(--muted)}.plans-heading button,.manual-start button{display:inline-flex;align-items:center;gap:8px;min-height:var(--control-height)}.plan-workspace-section{min-width:0}.manual-layout{display:grid;gap:16px;align-items:start}.manual-layout.is-editing{grid-template-columns:minmax(0,1fr) 400px}.manual-observation{min-width:0;border:1px solid var(--line);border-radius:16px;background:var(--surface);overflow:clip}.manual-observation :deep(.live-availability-panel){border:0;border-radius:0;margin:0;box-shadow:none;padding:16px 16px}.manual-start{display:flex;justify-content:space-between;align-items:center;gap:16px;border-top:1px solid var(--line);padding:16px 16px;font-size:13px}.plan-edit-section{min-width:0;margin:0}.plan-edit-section :deep(.plan-editor){padding:16px}.window-details{font-size:13px;color:var(--muted);margin-top:8px}.window-details>summary{cursor:pointer;min-height:var(--control-height);display:flex;align-items:center;gap:8px}.plan-reference-details{margin:8px 0 16px;color:var(--muted);font-size:13px}.plan-reference-details>summary{display:flex;align-items:center;gap:8px;cursor:pointer;min-height:var(--control-height);width:fit-content}.plan-reference-details[open]>summary{margin-bottom:8px}.plan-reference-details :deep(.venue-catalog-status){margin-bottom:0}.plan-section-heading h2{font-size:18px;margin:0}.plan-card{padding:16px 0}.plan-section-heading button{min-width:44px;min-height:var(--control-height);display:grid;place-items:center}.plan-reference-details :deep(.availability-simulation){margin-top:0}.plan-reference-details :deep(.simulation-notice){padding:8px 16px;font-size:13px}.plan-draft-tag{font-size:12px;padding:8px 8px}.plan-card h3{font-size:17px}.plan-card p{font-size:14px}.plans-page>.panel{margin-bottom:16px}.plans-page>.form-success{padding:0;background:transparent;border:0;font-size:13px;margin:0 0 16px;color:var(--brand)}@media(max-width:1100px){.manual-layout.is-editing{grid-template-columns:minmax(0,1fr)}.plan-edit-section{max-width:none}}@media(max-width:600px){.plans-heading h1{font-size:23px}.intent-badge{display:none}.manual-observation :deep(.live-availability-panel){padding:16px}.manual-start{padding:16px}.plan-edit-section :deep(.plan-editor){padding:16px}}

.manual-plan-card{min-width:0;border:1px solid var(--line);border-radius:16px;background:var(--surface)}.manual-plan-card>.selection-toolbar{border:0;border-bottom:1px solid var(--line);border-radius:16px 16px 0 0;margin:0}.manual-plan-card :deep(.manual-queue-workspace){border:0;border-radius:0 0 16px 16px}
.selection-toolbar{display:flex;align-items:center;gap:8px;background:var(--surface);border:1px solid var(--line);border-radius:8px;margin-bottom:16px;padding-right:16px}.selection-toolbar>.booking-date-strip{flex:1;border:0;padding:8px 16px}.selection-toolbar>button{display:flex;align-items:center;gap:8px;white-space:nowrap;min-height:40px}.selection-empty{padding:48px 16px;text-align:center;border:1px dashed var(--line);border-radius:8px;color:var(--muted)}.selection-empty>.app-icon{width:30px;height:30px}.query-workspace{min-width:0}.plan-edit-section{max-width:100%}.plan-edit-section :deep(.plan-fieldset){grid-template-columns:repeat(2,minmax(0,1fr))}.plan-edit-section :deep(.plan-fieldset>.plan-two-columns){grid-column:1/-1}.plan-edit-section :deep(.plan-fieldset>#plan-preferred_start_times){grid-column:1/-1}.plan-edit-section :deep(.plan-fieldset>.grid-apply-confirmation),.plan-edit-section :deep(.plan-fieldset>.editor-disclosure){grid-column:1/-1}.plan-section-heading>button[data-testid=new-current-plan]{margin-left:auto;display:flex;gap:8px;font-size:13px}.plan-section-heading{flex-wrap:nowrap}@media(max-width:650px){.selection-toolbar{flex-wrap:wrap;padding:8px}.selection-toolbar>.booking-date-strip{flex-basis:100%;padding:0}.selection-toolbar>button{margin-left:auto}.plan-edit-section :deep(.plan-fieldset){grid-template-columns:minmax(0,1fr)}}
</style>

<style scoped>
.current-queues{margin-top:16px}.current-queues h2,.queue-history h2{font-size:18px}.current-queues article{padding:16px 0;border-top:1px solid var(--line)}.current-queues article :deep(.queue-preview){grid-template-columns:repeat(2,minmax(0,1fr))}.current-queues h3{font-size:14px}.queue-history details>summary{min-height:var(--control-height);display:flex;align-items:center;cursor:pointer}.queue-history :deep(.queue-preview){margin:8px 0}@media(max-width:600px){.current-queues article :deep(.queue-preview){grid-template-columns:minmax(0,1fr)}}
</style>

<style scoped>
.ticket-filter-bar{display:grid;grid-template-columns:minmax(360px,380px) minmax(170px,200px) max-content minmax(100px,1fr);gap:8px;align-items:center;padding:8px 16px;border:1px solid var(--line);border-radius:8px;background:var(--surface);margin-bottom:16px;min-width:0}.ticket-filter-credential,.ticket-filter-date{min-width:0}.ticket-filter-bar :deep(.plan-credential-control){max-width:100%;min-width:0}.ticket-filter-bar :deep(.credential-popover>summary){min-height:var(--control-height)}.ticket-filter-bar :deep(.credential-popover>summary span){max-width:160px}.ticket-filter-date{display:flex;align-items:center;gap:8px;min-width:0;color:var(--muted)}.ticket-filter-bar input{min-height:var(--control-height);width:100%;min-width:0;padding:8px 8px;border:1px solid var(--line);border-radius:8px;color:var(--ink);background:var(--surface);font:inherit;font-size:14px}.ticket-filter-bar .ticket-filter-all,.ticket-filter-meta button{min-height:var(--control-height);font-size:13px;padding:8px 8px;white-space:nowrap}.ticket-filter-meta{display:flex;align-items:center;justify-content:flex-end;gap:8px;min-width:0}.ticket-filter-count{font-size:13px;color:var(--muted);white-space:nowrap}.ticket-delete-plan{display:flex;gap:8px;align-items:center;flex-wrap:wrap;font-size:13px}.plan-card{padding:8px 0}.plan-card h3{font-size:15px;margin:8px 0}.plan-card p{font-size:12px}.plan-actions button{min-height:var(--control-height);padding:8px 8px;font-size:12px}@media(max-width:1100px){.ticket-filter-bar{grid-template-columns:minmax(0,1fr) minmax(170px,1fr)}.ticket-filter-meta{grid-column:1/-1;justify-content:flex-end}}@media(max-width:460px){.ticket-filter-bar{grid-template-columns:minmax(0,1fr);padding:8px;gap:8px}.ticket-filter-credential,.ticket-filter-date,.ticket-filter-all,.ticket-filter-meta{grid-column:1}.ticket-filter-bar :deep(.plan-credential-control){flex-wrap:wrap}.ticket-filter-meta{justify-content:space-between}}
.execution-settings-disclosure { margin:12px 0; }.execution-settings-disclosure :deep(.execution-settings) { margin:0; padding:0; border:0; box-shadow:none; }
.plan-empty-state { display:flex; align-items:center; justify-content:center; gap:8px; margin:12px 0; padding:20px; border:1px dashed var(--line); border-radius:20px; color:var(--muted); background:var(--surface); font-size:13px; }
@media(max-width:600px) {
 .ticket-filter-bar { grid-template-columns:minmax(0,1fr) auto auto; gap:8px; padding:12px; }
 .ticket-filter-credential { grid-column:1/-1; }
 .ticket-filter-date { grid-column:1; min-width:0; }
 .ticket-filter-all { grid-column:2; width:auto; }
 .ticket-filter-meta { grid-column:3; width:auto; gap:4px; margin-left:auto; }
}
@media(max-width:360px) {
 .ticket-filter-bar { grid-template-columns:minmax(0,1fr) auto; }
 .ticket-filter-date { grid-column:1; }
 .ticket-filter-meta { grid-column:1/-1; }
}
</style>
