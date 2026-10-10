<script setup>
import { inject } from 'vue';
import PageHeader from '../PageHeader.vue';
import PlanForm from './PlanForm.vue';
import PlanHistory from './PlanHistory.vue';
import PlanSnapshotDetails from './PlanSnapshotDetails.vue';
import BookingWindowStatus from './BookingWindowStatus.vue';
import ProposalAssistant from './ProposalAssistant.vue';
import { usePlans } from '../../composables/usePlans.js';
const session=inject('sessionStore'),api=inject('planApi'),proposalApi=inject('planningProposalApi');
const {plans,source,listStatus,metadataError,saving,message,saveError,fields,conflict,latest,latestError,history,historyPlanId,historyStatus,windowState,windowError,uncertain,authorized,canCreate,refresh,initialize,startNew,edit,cancel,updateWindow,save,viewLatest,adoptLatest,showHistory,closeHistory,acknowledgeUncertain}=usePlans(api,session);
</script>
<template>
 <div class="plans-page">
  <PageHeader eyebrow="预约意向" title="我的预约计划" description="提前整理日期、时间和人工场地偏好，保存每一次明确的修改。"><button data-testid="new-plan" class="primary-button" type="button" :disabled="!canCreate" @click="startNew">新建预约计划</button></PageHeader>
  <p class="plan-notice">当前仅保存预约意向，场馆和场地尚未核验，不会自动查询或预约。</p>
  <div v-if="!authorized" class="panel"><p role="alert">{{ session?.status==='unauthenticated' ? '登录状态已失效，请重新登录。' : '暂时无法确认登录状态，请重试。' }}</p></div>
  <template v-else>
   <ProposalAssistant v-if="proposalApi" :plans="plans" :plan-api="api" :proposal-api="proposalApi" :session="session" @refresh-request="refresh" />
   <p v-if="metadataError" class="form-error" role="alert">{{ metadataError }} <button class="secondary-button" type="button" @click="initialize">重新读取配置</button></p>
   <p v-if="message" class="form-success" role="status">{{ message }}</p>
   <div v-if="saveError" class="plan-feedback" :class="conflict?'plan-conflict':''" role="alert"><p>{{ saveError }}</p><button v-if="source?.planId && (conflict || uncertain)" class="secondary-button" data-testid="view-latest" type="button" @click="viewLatest">查看最新版本</button><template v-if="uncertain"><button class="secondary-button" type="button" @click="refresh">读取计划列表核对</button><button class="secondary-button" type="button" @click="acknowledgeUncertain">已核对，允许再次保存</button></template></div>
   <p v-if="latestError" class="form-error" role="alert">{{ latestError }}</p>
   <section v-if="latest" class="panel latest-plan" aria-label="最新版本预览"><h2>最新版本 {{ latest.version }}（独立预览）</h2><PlanSnapshotDetails :snapshot="latest" /><p class="muted">采用最新版本将替换下方未保存内容，请先比较并保留需要的文字。</p><button data-testid="adopt-latest" class="secondary-button" type="button" :disabled="saving" @click="adoptLatest">采用最新版本，替换表单</button></section>
   <div v-if="source" class="plan-edit-section"><PlanForm :source="source" :busy="saving" :save-blocked="conflict || uncertain" :fields="fields" @save="save" @cancel="cancel" @target-change="updateWindow" /><BookingWindowStatus :state="windowState" :error="windowError" /></div>
   <section class="panel" aria-labelledby="plans-list-title"><div class="plan-section-heading"><h2 id="plans-list-title">已保存的预约意向</h2><button data-testid="refresh-plans" class="secondary-button" type="button" :disabled="saving || listStatus==='loading'" @click="refresh">刷新计划</button></div>
    <p v-if="listStatus==='loading'" class="muted" role="status">正在读取计划…</p>
    <p v-else-if="listStatus==='error'" class="form-error" role="alert">计划读取失败，请检查网络后刷新重试。</p>
    <p v-else-if="listStatus==='ready' && !plans.length" class="plan-empty">还没有预约计划。可以先保存未来日期的人工意向。</p>
    <div v-else class="plan-list"><article v-for="plan in plans" :key="plan.plan_id" class="plan-card"><div><span class="plan-draft-tag">未绑定草稿</span><h3>{{ plan.intent.venue_preference }}</h3><p>{{ plan.intent.target_date }} · {{ plan.intent.preferred_start_times.join(' → ') }} · {{ plan.intent.duration_minutes }} 分钟</p><p class="muted">版本 {{ plan.version }} · {{ plan.context.timezone_name }} · {{ plan.booking_window.can_query ? '处于日历窗口，尚未核验' : '当前不可查询' }}</p></div><div class="plan-actions"><button data-testid="edit-plan" class="secondary-button" type="button" :disabled="saving" @click="edit(plan)">编辑计划</button><button data-testid="history-plan" class="text-button" type="button" :disabled="saving" @click="showHistory(plan.plan_id)">版本历史</button></div></article></div>
   </section>
   <PlanHistory v-if="historyPlanId" :revisions="history" :status="historyStatus" @close="closeHistory" @retry="showHistory(historyPlanId)" />
  </template>
 </div>
</template>
<style>
.plans-page{min-width:0}.plans-page>.panel,.plan-edit-section{margin-bottom:22px}.plan-notice{padding:16px 20px;border-radius:12px;border:1px solid var(--line);background:var(--brand-soft);color:var(--brand-dark);margin:0 0 24px;line-height:1.7}.plan-section-heading{display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap}.plan-section-heading>div{min-width:0}.plan-list{display:grid;margin-top:18px}.plan-card{display:flex;align-items:center;justify-content:space-between;gap:20px;border-top:1px solid var(--line);padding:22px 0;min-width:0}.plan-card>div{min-width:0}.plan-card h3{margin:8px 0;overflow-wrap:anywhere}.plan-card p{margin:6px 0;overflow-wrap:anywhere}.plan-draft-tag{display:inline-block;color:var(--brand-dark);background:var(--brand-soft);padding:4px 10px;font-size:13px;border-radius:6px}.plan-actions{display:flex;flex-wrap:wrap;gap:10px;flex-shrink:0}.plan-empty{padding:24px 0;color:var(--muted)}.plan-feedback{border:1px solid var(--danger);background:var(--danger-soft);border-radius:12px;padding:18px;margin:0 0 20px;line-height:1.7}.plan-feedback button{margin:4px 8px 4px 0}.plan-feedback p{margin:0 0 10px}.plan-conflict{background:var(--warning-soft);border-color:var(--warning);color:var(--warning)}@media(max-width:700px){.plan-card{flex-direction:column;align-items:stretch}.plan-actions{flex-shrink:1}.plans-page .panel{padding:20px}}
</style>
