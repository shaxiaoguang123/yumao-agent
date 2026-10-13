<script setup>
import { computed, inject, shallowRef, watch } from 'vue';
import PageHeader from '../PageHeader.vue';
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
import { usePlans } from '../../composables/usePlans.js';
const session=inject('sessionStore'),api=inject('planApi'),proposalApi=inject('planningProposalApi');
const simulationApi=inject('availabilitySimulationApi',null);
const liveApi=inject('liveAvailabilityApi',null),credentialApi=inject('credentialApi',null);
const {plans,defaultWindow,catalog,source,listStatus,metadataError,saving,message,saveError,fields,conflict,latest,latestError,history,historyPlanId,historyStatus,windowState,windowError,uncertain,authorized,canCreate,refresh,initialize,startNew,edit,cancel,updateWindow,save,viewLatest,adoptLatest,showHistory,closeHistory,acknowledgeUncertain,rememberDraft}=usePlans(api,session);
const liveDraft=shallowRef(null),activeSection=shallowRef('manual'),manualDate=shallowRef('');
watch(defaultWindow,value=>{
 if(!value){manualDate.value='';activeSection.value='manual';}
 else if(!source.value)manualDate.value=value.default_target_date||value.queryable_target_dates?.[2]||'';
},{flush:'sync',immediate:true});
watch(source,value=>{
 liveDraft.value=null;
 if(value){manualDate.value=value.draftState?.form?.target_date||value.intent.target_date;activeSection.value='manual';}
},{flush:'sync'});
function rememberLiveDraft(draft){rememberDraft(draft);liveDraft.value=draft;manualDate.value=draft.form.target_date;}
function createManualPlan(){activeSection.value='manual';startNew(manualDate.value||undefined);}
const liveContextKey=computed(()=>JSON.stringify({source:source.value,draft:liveDraft.value,date:manualDate.value,conflict:conflict.value,uncertain:uncertain.value}));
</script>
<template>
 <div class="plans-page">
  <PageHeader eyebrow="预约工作台" title="我的预约计划" description="人工看时段、Agent 整理意向、查看已保存计划。"><button data-testid="new-plan" class="primary-button" type="button" :disabled="!canCreate" @click="createManualPlan">新建预约计划</button></PageHeader>
  <p class="plan-notice">当前仅保存预约意向，场馆和场地尚未核验。官方只读查询需手动触发，不会自动预约。</p>
  <div v-if="!authorized" class="panel"><p role="alert">{{ session?.status==='unauthenticated' ? '登录状态已失效，请重新登录。' : '暂时无法确认登录状态，请重试。' }}</p></div>
  <template v-else>
   <PlanSectionTabs v-model="activeSection" :plan-count="plans.length" />
   <p v-if="metadataError" class="form-error" role="alert">{{ metadataError }} <button class="secondary-button" type="button" @click="initialize">重新读取配置</button></p>
   <p v-if="message" class="form-success" role="status">{{ message }}</p>
   <div v-if="saveError" class="plan-feedback" :class="conflict?'plan-conflict':''" role="alert"><p>{{ saveError }}</p><button v-if="source?.planId && (conflict || uncertain)" class="secondary-button" data-testid="view-latest" type="button" @click="viewLatest">查看最新版本</button><template v-if="uncertain"><button class="secondary-button" type="button" @click="refresh">读取计划列表核对</button><button class="secondary-button" type="button" @click="acknowledgeUncertain">已核对，允许再次保存</button></template></div>
   <p v-if="latestError" class="form-error" role="alert">{{ latestError }}</p>
   <section v-if="latest" class="panel latest-plan" aria-label="最新版本预览"><h2>最新版本 {{ latest.version }}（独立预览）</h2><PlanSnapshotDetails :snapshot="latest" /><p class="muted">采用最新版本将替换下方未保存内容，请先比较并保留需要的文字。</p><button data-testid="adopt-latest" class="secondary-button" type="button" :disabled="saving" @click="adoptLatest">采用最新版本，替换表单</button></section>
   <section v-show="activeSection==='manual'" id="plan-panel-manual" role="tabpanel" aria-labelledby="plan-tab-manual" class="plan-workspace-section">
    <BookingDateStrip v-model="manualDate" :state="defaultWindow" :busy="saving" />
    <LiveAvailabilityPanel v-if="liveApi && credentialApi" :api="liveApi" :credential-api="credentialApi" :session="session" :target-date="manualDate" :context-key="liveContextKey" />
    <div v-if="source" class="plan-edit-section"><PlanForm :source="source" :requested-date="manualDate" :busy="saving" :save-blocked="conflict || uncertain" :fields="fields" :grid-api="simulationApi" :session-key="session?.user?.user_id||''" @save="save" @cancel="cancel" @target-change="updateWindow" @draft-change="rememberLiveDraft" /><BookingWindowStatus :state="windowState" :error="windowError" /></div>
    <section v-else class="panel manual-start"><div><p class="eyebrow">人工预约意向</p><h2>查看时段，再整理你的偏好</h2><p class="muted">按官方日期栏查看今天、明天或后天。保存时明确一个首选场地、有序备选和时间范围。</p></div><button class="primary-button" data-testid="manual-create" type="button" :disabled="!canCreate" @click="createManualPlan">按查看日期新建意向</button></section>
    <details class="plan-reference-details"><summary>目录来源与历史数据预览</summary><VenueCatalogStatus v-if="catalog" :catalog="catalog" /><OfficialHistoryPreview v-if="simulationApi" :api="simulationApi" :session="session" /></details>
   </section>
   <section v-show="activeSection==='agent'" id="plan-panel-agent" role="tabpanel" aria-labelledby="plan-tab-agent" class="plan-workspace-section">
    <div class="plan-mode-heading"><h2>让 Agent 帮你整理预约意向</h2><p class="muted">描述需求，连续补充信息；查看提案并明确确认后才保存。预约执行尚未开放。</p></div>
    <ProposalAssistant v-if="proposalApi" :plans="plans" :plan-api="api" :proposal-api="proposalApi" :session="session" @refresh-request="refresh" />
    <p v-else class="panel muted">Agent 服务当前未配置，请先检查模型设置。</p>
   </section>
   <section v-show="activeSection==='current'" id="plan-panel-current" role="tabpanel" aria-labelledby="plan-tab-current" class="plan-workspace-section">
   <section class="panel" aria-labelledby="plans-list-title"><div class="plan-section-heading"><h2 id="plans-list-title">已保存的预约意向</h2><button data-testid="refresh-plans" class="secondary-button" type="button" :disabled="saving || listStatus==='loading'" @click="refresh">刷新计划</button></div>
    <p v-if="listStatus==='loading'" class="muted" role="status">正在读取计划…</p>
    <p v-else-if="listStatus==='error'" class="form-error" role="alert">计划读取失败，请检查网络后刷新重试。</p>
    <p v-else-if="listStatus==='ready' && !plans.length" class="plan-empty">还没有预约计划。可以先保存未来日期的人工意向。</p>
    <div v-else class="plan-list"><article v-for="plan in plans" :key="plan.plan_id" class="plan-card"><div><span class="plan-draft-tag">未绑定草稿</span><h3>{{ plan.intent.venue_preference }}</h3><p>{{ plan.intent.target_date }} · {{ plan.intent.preferred_start_times.join(' → ') }} · {{ plan.intent.duration_minutes }} 分钟</p><p class="muted">版本 {{ plan.version }} · {{ plan.context.timezone_name }} · {{ plan.booking_window.can_query ? '处于日历窗口，尚未核验' : '当前不可查询' }}</p></div><div class="plan-actions"><button data-testid="edit-plan" class="secondary-button" type="button" :disabled="saving" @click="edit(plan)">编辑计划</button><button data-testid="history-plan" class="text-button" type="button" :disabled="saving" @click="showHistory(plan.plan_id)">版本历史</button></div></article></div>
   </section>
   <PlanHistory v-if="historyPlanId" :revisions="history" :status="historyStatus" @close="closeHistory" @retry="showHistory(historyPlanId)" />
   <AvailabilitySimulationPanel v-if="simulationApi" :plans="plans" :api="simulationApi" :session="session" @refresh-request="refresh" />
   </section>
  </template>
 </div>
</template>
<style>
.plans-page{min-width:0}.plans-page>.panel,.plan-edit-section{margin-bottom:22px}.plan-notice{padding:16px 20px;border-radius:12px;border:1px solid var(--line);background:var(--brand-soft);color:var(--brand-dark);margin:0 0 24px;line-height:1.7}.plan-section-heading{display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap}.plan-section-heading>div{min-width:0}.plan-list{display:grid;margin-top:18px}.plan-card{display:flex;align-items:center;justify-content:space-between;gap:20px;border-top:1px solid var(--line);padding:22px 0;min-width:0}.plan-card>div{min-width:0}.plan-card h3{margin:8px 0;overflow-wrap:anywhere}.plan-card p{margin:6px 0;overflow-wrap:anywhere}.plan-draft-tag{display:inline-block;color:var(--brand-dark);background:var(--brand-soft);padding:4px 10px;font-size:13px;border-radius:6px}.plan-actions{display:flex;flex-wrap:wrap;gap:10px;flex-shrink:0}.plan-empty{padding:24px 0;color:var(--muted)}.plan-feedback{border:1px solid var(--danger);background:var(--danger-soft);border-radius:12px;padding:18px;margin:0 0 20px;line-height:1.7}.plan-feedback button{margin:4px 8px 4px 0}.plan-feedback p{margin:0 0 10px}.plan-conflict{background:var(--warning-soft);border-color:var(--warning);color:var(--warning)}@media(max-width:700px){.plan-card{flex-direction:column;align-items:stretch}.plan-actions{flex-shrink:1}.plans-page .panel{padding:20px}}
</style>
<style scoped>
.plan-workspace-section{min-width:0}.plan-mode-heading{margin:0 0 18px}.plan-mode-heading h2{margin:0 0 8px;font-size:22px}.plan-mode-heading p{margin:0;line-height:1.7}.manual-start{display:flex;justify-content:space-between;align-items:center;gap:20px;margin:18px 0}.manual-start h2{font-size:21px;margin:8px 0}.manual-start p{margin:0;line-height:1.7}.manual-start button{flex-shrink:0}.plan-reference-details{margin:18px 0 24px;border:1px solid var(--line);border-radius:12px;padding:16px;background:var(--surface)}.plan-reference-details>summary{cursor:pointer;color:var(--muted);font-size:14px;min-height:24px}.plan-reference-details[open]>summary{margin-bottom:18px}.plan-reference-details :deep(.venue-catalog-status){margin-bottom:0}@media(max-width:600px){.manual-start{flex-direction:column;align-items:stretch}.manual-start button{min-height:44px}}
</style>
