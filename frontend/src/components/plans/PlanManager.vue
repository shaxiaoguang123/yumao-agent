<script setup>
import { computed, inject, shallowRef, watch } from 'vue';
import { onBeforeRouteLeave } from 'vue-router';
import AppIcon from '../AppIcon.vue';
import PlanForm from './PlanForm.vue';
import PlanHistory from './PlanHistory.vue';
import PlanSnapshotDetails from './PlanSnapshotDetails.vue';
import BookingWindowStatus from './BookingWindowStatus.vue';
import ProposalAssistant from './ProposalAssistant.vue';
import AvailabilitySimulationPanel from './AvailabilitySimulationPanel.vue';
import VenueCatalogStatus from './VenueCatalogStatus.vue';
import OfficialHistoryPreview from './OfficialHistoryPreview.vue';
import LiveAvailabilityPanel from './LiveAvailabilityPanel.vue';
import PlanSectionTabs from './PlanSectionTabs.vue';
import BookingDateStrip from './BookingDateStrip.vue';
import ManualQueueWorkspace from './ManualQueueWorkspace.vue';
import ManualQueuePreview from './ManualQueuePreview.vue';
import PlanCredentialControl from './PlanCredentialControl.vue';
import { useManualQueue, queueEntries } from '../../composables/useManualQueue.js';
import { usePlans } from '../../composables/usePlans.js';
const session=inject('sessionStore'),api=inject('planApi'),proposalApi=inject('planningProposalApi',null);
const simulationApi=inject('availabilitySimulationApi',null);
const liveApi=inject('liveAvailabilityApi',null),credentialApi=inject('credentialApi',null);
const {plans,defaultWindow,catalog,source,listStatus,metadataError,saving,message,saveError,fields,conflict,latest,latestError,history,historyPlanId,historyStatus,windowState,windowError,uncertain,authorized,canCreate,refresh,initialize,startNew,edit,cancel,updateWindow,save,viewLatest,adoptLatest,showHistory,closeHistory,acknowledgeUncertain,rememberDraft}=usePlans(api,session);
const courtOptions=shallowRef([]),queryDate=shallowRef(''),selectedCredentialId=shallowRef(''),credentialRefreshKey=shallowRef(0);
const liveDraft=shallowRef(null),activeSection=shallowRef('query'),manualDate=shallowRef('');
const queueState=useManualQueue(api,session,()=>manualDate.value);
onBeforeRouteLeave(async()=>{if(!authorized.value||!queueState.dirty)return true;await queueState.flush();return !queueState.dirty;});
watch(defaultWindow,value=>{
 if(!value){manualDate.value='';queryDate.value='';activeSection.value='query';}
 else {if(!queryDate.value)queryDate.value=value.queryable_target_dates?.[2]||value.default_target_date||'';if(!source.value)manualDate.value=value.default_target_date||value.queryable_target_dates?.[2]||'';}
},{flush:'sync',immediate:true});
watch(source,value=>{
 liveDraft.value=null;
 if(value){activeSection.value='current';}
},{flush:'sync'});
function rememberLiveDraft(draft){rememberDraft(draft);liveDraft.value=draft;}
function createManualPlan(){activeSection.value='current';startNew(manualDate.value||undefined);}

function rememberCourtLabels(names){if(JSON.stringify(courtOptions.value)!==JSON.stringify(names))courtOptions.value=[...names];}
watch(()=>[session?.status,session?.user?.user_id,session?.invalidationEpoch],()=>{courtOptions.value=[];},{flush:'sync'});
const queryContextKey=computed(()=>JSON.stringify({user:session?.user?.user_id,epoch:session?.invalidationEpoch}));
</script>
<template>
 <div class="plans-page">
  <h1 class="sr-only">预约计划</h1>
  <div v-if="!authorized" class="panel"><p role="alert">{{ session?.status==='unauthenticated' ? '登录状态已失效，请重新登录。' : '暂时无法确认登录状态，请重试。' }}</p></div>
  <template v-else>
   <PlanSectionTabs v-model="activeSection" :plan-count="plans.length+queueState.queues.filter(q=>q.candidates.length).length" />
   <p v-if="metadataError" class="form-error" role="alert">{{ metadataError }} <button class="secondary-button" type="button" @click="initialize">重新读取配置</button></p>
   <p v-if="message" class="form-success" role="status">{{ message }}</p>
   <div v-if="saveError" class="plan-feedback" :class="conflict?'plan-conflict':''" role="alert"><p>{{ saveError }}</p><button v-if="source?.planId && (conflict || uncertain)" class="secondary-button" data-testid="view-latest" type="button" @click="viewLatest">查看最新版本</button><template v-if="uncertain"><button class="secondary-button" type="button" @click="refresh">读取计划列表核对</button><button class="secondary-button" type="button" @click="acknowledgeUncertain">已核对，允许再次保存</button></template></div>
   <p v-if="latestError" class="form-error" role="alert">{{ latestError }}</p>
   <section v-if="latest" class="panel latest-plan" aria-label="最新版本预览"><h2>最新版本 {{ latest.version }}（独立预览）</h2><PlanSnapshotDetails :snapshot="latest" /><p class="muted">采用最新版本将替换下方未保存内容，请先比较并保留需要的文字。</p><button data-testid="adopt-latest" class="secondary-button" type="button" :disabled="saving" @click="adoptLatest">采用最新版本，替换表单</button></section>
   <section v-show="activeSection==='query'" id="plan-panel-query" role="tabpanel" aria-labelledby="plan-tab-query" class="plan-workspace-section query-workspace">
    <LiveAvailabilityPanel v-if="liveApi && credentialApi" v-model:credential-id="selectedCredentialId" :credential-refresh-key="credentialRefreshKey" :api="liveApi" :credential-api="credentialApi" :session="session" :calendar-state="defaultWindow" :target-date="queryDate" :context-key="queryContextKey" @date-change="queryDate=$event" @court-labels="rememberCourtLabels" />
    <BookingDateStrip v-else v-model="queryDate" :state="defaultWindow" />
    <details class="plan-reference-details"><summary aria-label="目录来源与历史数据预览" title="目录来源与历史数据预览"><AppIcon name="info" />数据资料</summary><VenueCatalogStatus v-if="catalog" :catalog="catalog" /><OfficialHistoryPreview v-if="simulationApi" :api="simulationApi" :session="session" /></details>
   </section>
   <section v-show="activeSection==='manual'" id="plan-panel-manual" role="tabpanel" aria-labelledby="plan-tab-manual" class="plan-workspace-section">
    <div class="selection-toolbar"><BookingDateStrip v-model="manualDate" :state="defaultWindow" :busy="saving||queueState.dateLocked" @refresh="queueState.load"><template #actions><PlanCredentialControl v-if="credentialApi" v-model="selectedCredentialId" :api="credentialApi" :session="session" :timezone-name="defaultWindow?.business_timezone_name||'Asia/Shanghai'" @updated="credentialRefreshKey++" /></template></BookingDateStrip></div>
    <ManualQueueWorkspace :state="queueState" :court-names="courtOptions" :target-date="manualDate" />
   </section>
   <section v-show="activeSection==='agent'" id="plan-panel-agent" role="tabpanel" aria-labelledby="plan-tab-agent" class="plan-workspace-section">
    <ProposalAssistant v-if="proposalApi" :plans="plans" :plan-api="api" :proposal-api="proposalApi" :session="session" @refresh-request="refresh" />
    <p v-else class="panel muted">Agent 服务当前未配置，请先检查模型设置。</p>
   </section>
   <section v-show="activeSection==='current'" id="plan-panel-current" role="tabpanel" aria-labelledby="plan-tab-current" class="plan-workspace-section">
       <div v-if="source" class="plan-edit-section"><PlanForm :court-options="courtOptions" :source="source"  :busy="saving" :save-blocked="conflict || uncertain" :fields="fields" :grid-api="simulationApi" :session-key="session?.user?.user_id||''" @save="save" @cancel="cancel" @target-change="updateWindow" @draft-change="rememberLiveDraft" /><details class="window-details"><summary>日期窗口</summary><BookingWindowStatus :state="windowState" :error="windowError" /></details></div>

   <section v-if="plans.length||!queueState.queues.some(q=>q.candidates.length)" class="panel" aria-labelledby="plans-list-title"><div class="plan-section-heading"><h2 id="plans-list-title">我的计划</h2><button data-testid="new-plan" class="secondary-button" type="button" :disabled="!canCreate" @click="createManualPlan"><AppIcon name="plus" />新建计划</button><button data-testid="refresh-plans" class="secondary-button" type="button" :disabled="saving || listStatus==='loading'" @click="refresh();queueState.refreshList()" aria-label="刷新计划" title="刷新计划"><AppIcon name="refresh" /></button></div>
    <p v-if="listStatus==='loading'" class="muted" role="status">正在读取计划…</p>
    <p v-else-if="listStatus==='error'" class="form-error" role="alert">计划读取失败，请检查网络后刷新重试。</p>
    <p v-else-if="listStatus==='ready' && !plans.length" class="plan-empty">还没有预约计划。可以先保存未来日期的人工意向。</p>
    <div v-else class="plan-list"><article v-for="plan in plans" :key="plan.plan_id" class="plan-card"><div><span class="plan-draft-tag">未绑定</span><h3>{{ plan.intent.venue_preference }}</h3><p>{{ plan.intent.target_date }} · {{ plan.intent.preferred_start_times.join(' → ') }} · {{ plan.intent.duration_minutes }} 分钟</p><p class="muted">版本 {{ plan.version }} · {{ plan.intent.court_preferences.join(' → ') || '场地未指定' }}</p></div><div class="plan-actions"><button data-testid="edit-plan" class="secondary-button" type="button" :disabled="saving" @click="edit(plan)">编辑计划</button><button data-testid="history-plan" class="text-button" type="button" :disabled="saving" @click="showHistory(plan.plan_id)">版本历史</button></div></article></div>
   </section>
   <section v-if="queueState.queues.some(q=>q.candidates.length)" class="panel current-queues" aria-label="人工候选队列"><h2>人工候选队列</h2><article v-for="queue in queueState.queues.filter(q=>q.candidates.length)" :key="queue.plan_id"><div class="plan-section-heading"><h3>{{ queue.target_date }} · v{{ queue.version }}</h3><button type="button" class="secondary-button" :disabled="queueState.dateLocked" @click="manualDate=queue.target_date;activeSection='manual'">继续选择</button><button type="button" class="text-button" @click="queueState.showHistory(queue.target_date)">版本历史</button></div><ManualQueuePreview :entries="queueEntries(queue)" readonly /></article></section>
   <section v-if="queueState.history" class="panel queue-history"><div class="plan-section-heading"><h2>队列版本历史</h2><button type="button" class="text-button" @click="queueState.history=null">关闭历史</button></div><details v-for="revision in queueState.history" :key="revision.revision_id"><summary>版本 {{ revision.revision_number }} · {{ revision.target_date }}</summary><ManualQueuePreview :entries="queueEntries(revision)" readonly /></details></section><p v-if="queueState.historyError" class="form-error" role="alert">{{ queueState.historyError }}</p>
   <PlanHistory v-if="historyPlanId" :revisions="history" :status="historyStatus" @close="closeHistory" @retry="showHistory(historyPlanId)" />
   <details class="plan-reference-details" data-testid="simulation-disclosure"><summary><AppIcon name="court" />模拟匹配</summary><AvailabilitySimulationPanel v-if="simulationApi" :plans="plans" :api="simulationApi" :session="session" @refresh-request="refresh" /></details>
   </section>
  </template>
 </div>
</template>
<style>
.plans-page{min-width:0}.plans-page>.panel,.plan-edit-section{margin-bottom:22px}.plan-notice{padding:16px 20px;border-radius:12px;border:1px solid var(--line);background:var(--brand-soft);color:var(--brand-dark);margin:0 0 24px;line-height:1.7}.plan-section-heading{display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap}.plan-section-heading>div{min-width:0}.plan-list{display:grid;margin-top:18px}.plan-card{display:flex;align-items:center;justify-content:space-between;gap:20px;border-top:1px solid var(--line);padding:22px 0;min-width:0}.plan-card>div{min-width:0}.plan-card h3{margin:8px 0;overflow-wrap:anywhere}.plan-card p{margin:6px 0;overflow-wrap:anywhere}.plan-draft-tag{display:inline-block;color:var(--brand-dark);background:var(--brand-soft);padding:4px 10px;font-size:13px;border-radius:6px}.plan-actions{display:flex;flex-wrap:wrap;gap:10px;flex-shrink:0}.plan-empty{padding:24px 0;color:var(--muted)}.plan-feedback{border:1px solid var(--danger);background:var(--danger-soft);border-radius:12px;padding:18px;margin:0 0 20px;line-height:1.7}.plan-feedback button{margin:4px 8px 4px 0}.plan-feedback p{margin:0 0 10px}.plan-conflict{background:var(--warning-soft);border-color:var(--warning);color:var(--warning)}@media(max-width:700px){.plan-card{flex-direction:column;align-items:stretch}.plan-actions{flex-shrink:1}.plans-page .panel{padding:20px}}
</style>
<style scoped>
.plans-heading{display:flex;align-items:center;justify-content:space-between;gap:12px;margin-bottom:12px}.plans-heading h1{font-size:26px;margin:0;letter-spacing:-.03em}.plans-heading-actions{display:flex;align-items:center;gap:12px}.intent-badge{font-size:12px;color:var(--muted)}.plans-heading button,.manual-start button{display:inline-flex;align-items:center;gap:6px;min-height:44px}.plan-workspace-section{min-width:0}.manual-layout{display:grid;gap:16px;align-items:start}.manual-layout.is-editing{grid-template-columns:minmax(0,1fr) 400px}.manual-observation{min-width:0;border:1px solid var(--line);border-radius:12px;background:var(--surface);overflow:clip}.manual-observation :deep(.live-availability-panel){border:0;border-radius:0;margin:0;box-shadow:none;padding:16px 20px}.manual-start{display:flex;justify-content:space-between;align-items:center;gap:12px;border-top:1px solid var(--line);padding:12px 20px;font-size:13px}.plan-edit-section{min-width:0;margin:0}.plan-edit-section :deep(.plan-editor){padding:20px}.window-details{font-size:13px;color:var(--muted);margin-top:8px}.window-details>summary{cursor:pointer;min-height:44px;display:flex;align-items:center;gap:6px}.plan-reference-details{margin:8px 0 16px;color:var(--muted);font-size:13px}.plan-reference-details>summary{display:flex;align-items:center;gap:6px;cursor:pointer;min-height:44px;width:fit-content}.plan-reference-details[open]>summary{margin-bottom:8px}.plan-reference-details :deep(.venue-catalog-status){margin-bottom:0}.plan-section-heading h2{font-size:18px;margin:0}.plan-card{padding:16px 0}.plan-section-heading button{min-width:44px;min-height:44px;display:grid;place-items:center}.plan-reference-details :deep(.availability-simulation){margin-top:0}.plan-reference-details :deep(.simulation-notice){padding:8px 12px;font-size:13px}.plan-draft-tag{font-size:12px;padding:2px 7px}.plan-card h3{font-size:17px}.plan-card p{font-size:14px}.plans-page>.panel{margin-bottom:16px}.plans-page>.form-success{padding:0;background:transparent;border:0;font-size:13px;margin:0 0 12px;color:var(--brand)}@media(max-width:1100px){.manual-layout.is-editing{grid-template-columns:minmax(0,1fr)}.plan-edit-section{max-width:none}}@media(max-width:600px){.plans-heading h1{font-size:23px}.intent-badge{display:none}.manual-observation :deep(.live-availability-panel){padding:12px}.manual-start{padding:12px}.plan-edit-section :deep(.plan-editor){padding:16px}}

.selection-toolbar{display:flex;align-items:center;gap:8px;background:var(--surface);border:1px solid var(--line);border-radius:10px;margin-bottom:12px;padding-right:12px}.selection-toolbar>.booking-date-strip{flex:1;border:0;padding:10px 12px}.selection-toolbar>button{display:flex;align-items:center;gap:5px;white-space:nowrap;min-height:40px}.selection-empty{padding:48px 20px;text-align:center;border:1px dashed var(--line);border-radius:10px;color:var(--muted)}.selection-empty>.app-icon{width:30px;height:30px}.query-workspace{min-width:0}.plan-edit-section{max-width:100%}.plan-edit-section :deep(.plan-fieldset){grid-template-columns:repeat(2,minmax(0,1fr))}.plan-edit-section :deep(.plan-fieldset>.plan-two-columns){grid-column:1/-1}.plan-edit-section :deep(.plan-fieldset>#plan-preferred_start_times){grid-column:1/-1}.plan-edit-section :deep(.plan-fieldset>.grid-apply-confirmation),.plan-edit-section :deep(.plan-fieldset>.editor-disclosure){grid-column:1/-1}.plan-section-heading>button[data-testid=new-current-plan]{margin-left:auto;display:flex;gap:5px;font-size:13px}.plan-section-heading{flex-wrap:nowrap}@media(max-width:650px){.selection-toolbar{flex-wrap:wrap;padding:8px}.selection-toolbar>.booking-date-strip{flex-basis:100%;padding:0}.selection-toolbar>button{margin-left:auto}.plan-edit-section :deep(.plan-fieldset){grid-template-columns:minmax(0,1fr)}}
</style>

<style scoped>
.current-queues{margin-top:12px}.current-queues h2,.queue-history h2{font-size:18px}.current-queues article{padding:12px 0;border-top:1px solid var(--line)}.current-queues article :deep(.queue-preview){grid-template-columns:repeat(2,minmax(0,1fr))}.current-queues h3{font-size:14px}.queue-history details>summary{min-height:44px;display:flex;align-items:center;cursor:pointer}.queue-history :deep(.queue-preview){margin:10px 0}@media(max-width:600px){.current-queues article :deep(.queue-preview){grid-template-columns:minmax(0,1fr)}}
</style>
