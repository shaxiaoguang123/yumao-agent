<script setup>
import { computed, onBeforeUnmount, ref, shallowRef, watch } from 'vue';
import { RouterLink } from 'vue-router';
import PlanSnapshotDetails from './PlanSnapshotDetails.vue';
import BookingWindowStatus from './BookingWindowStatus.vue';

const props=defineProps({plans:{type:Array,default:()=>[]},planApi:{type:Object,required:true},proposalApi:{type:Object,required:true},session:{type:Object,required:true}});
const emit=defineEmits(['saved','refresh-request']);
const message=ref(''),targetId=shallowRef(''),proposal=shallowRef(null),status=shallowRef('idle');
const questions=ref([]),error=shallowRef(''),savedNotice=shallowRef(''),latest=shallowRef(null),latestError=shallowRef('');
const generatedFor=shallowRef(null),busySaving=shallowRef(false),needsRegeneration=shallowRef(false);
const uncertainSave=shallowRef(false),verificationLoading=shallowRef(false),verificationComplete=shallowRef(false),verificationResult=shallowRef(null);
const ownSavedVersion=shallowRef(null);
const labels={target_date:'目标日期',preferred_start_times:'开始时间偏好',duration_minutes:'预约时长',venue_preference:'场馆偏好',court_preferences:'场地偏好',fallback_policy:'备用策略',price_ceiling_minor:'价格上限'};
const currentTarget=computed(()=>targetId.value||null);
const selectedPlan=computed(()=>props.plans.find(plan=>plan.plan_id===targetId.value)||null);
const targetChanged=computed(()=>Boolean(generatedFor.value)&&(
 generatedFor.value.planId!==currentTarget.value
 || (currentTarget.value&&selectedPlan.value&&generatedFor.value.listVersion!==selectedPlan.value.version)
 || generatedFor.value.message!==message.value.trim()
));
const canSave=computed(()=>status.value==='ready'&&proposal.value?.can_book===false&&generatedFor.value&&!targetChanged.value&&!needsRegeneration.value&&!uncertainSave.value&&!busySaving.value);
const questionList=computed(()=>Array.isArray(questions.value)?questions.value:[]);
let alive=true,epoch=0,requestId=0;
const authorized=()=>props.session.status==='authenticated'&&Boolean(props.session.user?.user_id);
function valid(generation,userId,csrfToken){return alive&&generation===epoch&&authorized()&&props.session.user?.user_id===userId&&props.session.csrfToken===csrfToken;}
function resetForSession(values,previous){
 epoch++;requestId++;proposal.value=null;generatedFor.value=null;status.value='idle';questions.value=[];latest.value=null;latestError.value='';error.value='';savedNotice.value='';needsRegeneration.value=false;uncertainSave.value=false;verificationLoading.value=false;verificationComplete.value=false;verificationResult.value=null;ownSavedVersion.value=null;busySaving.value=false;
 if(previous&&previous[1]!==values[1]){message.value='';targetId.value='';}
}
watch(()=>[props.session.status,props.session.user?.user_id,props.session.csrfToken],resetForSession,{flush:'sync'});
watch(()=>[message.value,targetId.value,selectedPlan.value?.version],(current,previous)=>{
 requestId++;
 if(status.value==='generating')status.value='idle';
 const inputOrTargetChanged=current[0]!==previous[0]||current[1]!==previous[1];
 if(inputOrTargetChanged){savedNotice.value='';ownSavedVersion.value=null;return;}
 const versionChanged=current[2]!==previous[2];
 if(versionChanged){
  const ownUpdate=ownSavedVersion.value&&current[1]===ownSavedVersion.value.planId&&current[2]===ownSavedVersion.value.version;
  if(ownUpdate)ownSavedVersion.value=null;
  else{savedNotice.value='';ownSavedVersion.value=null;}
 }
},{flush:'sync'});
function clearProposal(){if(uncertainSave.value)return;proposal.value=null;questions.value=[];status.value='idle';generatedFor.value=null;latest.value=null;latestError.value='';error.value='';savedNotice.value='';needsRegeneration.value=false;}
function formatValue(field,value,context){
 if(value===null||value===undefined)return '未设置';
 if(field==='target_date'&&typeof value==='string'&&/^\d{4}-\d{2}-\d{2}$/.test(value))return `${value.slice(0,4)}年${value.slice(5,7)}月${value.slice(8,10)}日`;
 if(field==='preferred_start_times'&&Array.isArray(value))return value.length?`${value.join(' → ')}（按优先顺序）`:'未指定';
 if(field==='court_preferences'&&Array.isArray(value))return value.length?`${value.join(' → ')}（按偏好顺序）`:'未指定具体场地';
 if(field==='duration_minutes')return `${value} 分钟`;
 if(field==='fallback_policy'&&value&&typeof value==='object'){
  const court=value.allow_any_court_in_venue?'愿意考虑同场馆其他场地':'只考虑填写的场地';
  const time=value.allow_time_shift&&value.allowed_start_time_range
   ?`允许开始时间在 ${value.allowed_start_time_range.start} 至 ${value.allowed_start_time_range.end} 浮动`
   :'开始时间不浮动';
  return `${court}；${time}`;
 }
 if(field==='price_ceiling_minor'&&Number.isSafeInteger(value)){
  const exponent=Number.isInteger(context?.currency_minor_unit_exponent)?context.currency_minor_unit_exponent:0;
  const raw=BigInt(value).toString();
  const amount=exponent===0?raw:(raw.padStart(exponent+1,'0').slice(0,-exponent)+'.'+raw.padStart(exponent+1,'0').slice(-exponent));
  return `${amount}${context?.currency_code?` ${context.currency_code}`:''}`;
 }
 if(typeof value==='object')return '有更新';
 return String(value);
}
async function generate({forceLatest=false}={}){
 if(!authorized()||status.value==='generating'||busySaving.value||uncertainSave.value||!message.value.trim())return;
 const generation=epoch,id=props.session.user.user_id,csrf=props.session.csrfToken,sequence=++requestId,selectedId=targetId.value||null,userMessage=message.value.trim(),listVersion=selectedPlan.value?.version??null;
 status.value='generating';error.value='';savedNotice.value='';latestError.value='';questions.value=[];proposal.value=null;generatedFor.value=null;needsRegeneration.value=false;uncertainSave.value=false;verificationComplete.value=false;verificationResult.value=null;
 try{
  let plan=null;
  if(selectedId){const response=await props.planApi.get(selectedId);if(!valid(generation,id,csrf)||sequence!==requestId)return;plan=response.plan;}
  if(forceLatest&&plan)latest.value=plan;
  const baseVersion=plan?.version??null;
  const result=await props.proposalApi.generate(userMessage,selectedId,baseVersion);
  if(!valid(generation,id,csrf)||sequence!==requestId)return;
  proposal.value=result.proposal;questions.value=result.questions||[];status.value=result.status;
  generatedFor.value={message:userMessage,planId:selectedId,baseVersion:result.proposal?.base_version??baseVersion,listVersion};
  if(forceLatest&&plan)latest.value=plan;
 }catch(err){
  if(!valid(generation,id,csrf)||sequence!==requestId)return;
  status.value='error';error.value=err?.code==='provider_not_configured'?'尚未配置 AI 模型，请先完成设置。':err?.code==='provider_api_key_required'?'当前模型缺少 API Key，请前往模型设置补充密钥。':err?.code==='plan_version_conflict'?'计划版本已变化。你的描述仍保留，请读取最新版本并重新生成。':err?.status===409?'模型设置或请求状态需要检查，请先查看错误提示后重试。':'生成建议失败，请检查模型设置或稍后重试。';
  if(err?.code==='plan_version_conflict')needsRegeneration.value=true;
 }finally{if(valid(generation,id,csrf)&&sequence===requestId&&status.value==='generating')status.value='idle';}
}
async function readLatestAndRegenerate(){
 if(!targetId.value||!authorized()||busySaving.value)return;
 const generation=epoch,id=props.session.user.user_id,csrf=props.session.csrfToken,sequence=requestId,selected=targetId.value,capturedMessage=message.value.trim();
 latest.value=null;latestError.value='';error.value='';needsRegeneration.value=true;
 try{const result=await props.planApi.get(selected);if(!valid(generation,id,csrf)||sequence!==requestId||selected!==targetId.value||capturedMessage!==message.value.trim())return;latest.value=result.plan;await generate({forceLatest:true});}
 catch{if(valid(generation,id,csrf))latestError.value='最新版本读取失败，描述和当前建议仍保留。请重试。';}
}
async function saveProposal(){
 if(!canSave.value)return;const generation=epoch,id=props.session.user.user_id,csrf=props.session.csrfToken,captured=generatedFor.value;
 busySaving.value=true;error.value='';savedNotice.value='';
 try{
  const result=captured.planId
   ? await props.planApi.update(captured.planId,captured.baseVersion,proposal.value.intent)
   : await props.planApi.create(proposal.value.intent);
  if(!valid(generation,id,csrf))return;
  savedNotice.value=`预约意向已保存 · 版本 ${result.plan.version}`;ownSavedVersion.value=captured.planId?{planId:captured.planId,version:result.plan.version}:null;proposal.value=null;generatedFor.value=null;status.value='saved';needsRegeneration.value=false;emit('saved',result.plan);emit('refresh-request');
 }catch(err){
  if(!valid(generation,id,csrf))return;
  if(err?.code==='plan_version_conflict'){error.value='保存时检测到版本冲突。你的描述和建议均已保留。';needsRegeneration.value=true;}
  else if(err?.code==='provider_api_key_required'||err?.code==='provider_not_configured')error.value='当前模型缺少可用 API Key，请前往模型设置补充密钥后再重新生成。';
  else if(err?.status===400)error.value='预约意向未保存，请检查字段后重试；当前建议仍保留。';
  else if(err?.kind==='network'||err?.kind==='timeout'||!err?.status||err.status>=500){uncertainSave.value=true;verificationComplete.value=false;verificationResult.value=null;latest.value=null;latestError.value='';error.value='保存结果暂时无法确认。请先读取计划列表或最新版本，核对后再决定是否重试。';}
  else error.value='预约意向保存失败，当前建议仍保留。请检查错误后再试。';
 }finally{if(valid(generation,id,csrf))busySaving.value=false;}
}
async function verifyAmbiguousSave(){
 if(!uncertainSave.value||verificationLoading.value||!authorized())return;
 const generation=epoch,id=props.session.user.user_id,csrf=props.session.csrfToken,sequence=++requestId,selected=generatedFor.value?.planId||null;
 verificationLoading.value=true;verificationComplete.value=false;verificationResult.value=null;latestError.value='';
 try{
  if(selected){const response=await props.planApi.get(selected);if(!valid(generation,id,csrf)||sequence!==requestId)return;verificationResult.value={type:'plan',plan:response.plan};latest.value=response.plan;}
  else{const response=await props.planApi.list();if(!valid(generation,id,csrf)||sequence!==requestId)return;verificationResult.value={type:'list',plans:response.plans||[]};}
  verificationComplete.value=true;
 }catch{if(valid(generation,id,csrf)&&sequence===requestId)latestError.value='核对读取失败，描述和建议已保留；请重试读取。';}
 finally{if(valid(generation,id,csrf)&&sequence===requestId)verificationLoading.value=false;}
}
function acknowledgeAmbiguousSave(){if(uncertainSave.value&&verificationComplete.value){uncertainSave.value=false;error.value='';savedNotice.value='核对已完成。如仍需保存，请再次确认。';}}
function cancelProposal(){clearProposal();}
onBeforeUnmount(()=>{alive=false;epoch++;requestId++;});
</script>

<template>
 <section class="panel proposal-assistant" aria-labelledby="proposal-title">
  <div class="proposal-heading"><div><p class="eyebrow">AI辅助整理</p><h2 id="proposal-title">用自然语言整理预约意向</h2></div><span class="proposal-scope">仅生成草案</span></div>
  <p class="muted">描述你想保存的日期、时间、场馆或场地偏好。AI只会生成待确认的意向草案，不会预约、付款、创建任务或查询上游。</p>
  <label class="field">要整理的内容<textarea v-model="message" data-testid="proposal-message" rows="4" maxlength="4000" :disabled="busySaving||uncertainSave" placeholder="例如：把日期改成下周六晚上，优先 18:30，想约城北球馆的 6 号场。" /></label>
  <label class="field">应用到<select v-model="targetId" data-testid="proposal-target" :disabled="busySaving||uncertainSave"><option value="">新建预约计划</option><option v-for="plan in plans" :key="plan.plan_id" :value="plan.plan_id">编辑：{{ plan.intent.venue_preference }} · {{ plan.intent.target_date }} · 版本 {{ plan.version }}</option></select></label>
  <div class="proposal-actions"><button class="primary-button" data-testid="generate-proposal" type="button" :disabled="status==='generating'||busySaving||uncertainSave||!message.trim()" @click="generate()">{{ status==='generating'?'正在生成…':'生成建议预览' }}</button><RouterLink class="action-link" :to="{name:'ai-models'}">模型设置</RouterLink></div>
  <p v-if="error" class="proposal-feedback error" role="alert">{{ error }} <RouterLink v-if="error.includes('尚未配置')||error.includes('模型设置')||error.includes('密钥')" :to="{name:'ai-models'}">前往设置AI模型</RouterLink></p>
  <p v-if="latestError" class="proposal-feedback error" role="alert">{{ latestError }}</p><p v-if="savedNotice" class="proposal-feedback success" role="status">{{ savedNotice }}</p>
  <section v-if="uncertainSave" class="verification-panel" aria-label="保存结果核对">
   <h3>保存结果待核对</h3><p>为避免重复创建，请先读取列表或该计划最新版本。核对结果后，明确确认才会重新允许保存。</p>
   <button class="secondary-button" data-testid="verify-ambiguous-save" type="button" :disabled="verificationLoading" @click="verifyAmbiguousSave">{{ verificationLoading?'正在读取…':generatedFor?.planId?'读取最新版本':'读取计划列表' }}</button>
   <p v-if="verificationResult?.type==='list'" role="status">已读取计划列表，共 {{ verificationResult.plans.length }} 个预约计划。</p>
   <ul v-if="verificationResult?.type==='list'&&verificationResult.plans.length"><li v-for="plan in verificationResult.plans.slice(0,5)" :key="plan.plan_id">{{ plan.intent.venue_preference }} · {{ plan.intent.target_date }} · 版本 {{ plan.version }}</li></ul>
   <button class="primary-button" data-testid="acknowledge-save-check" type="button" :disabled="!verificationComplete" @click="acknowledgeAmbiguousSave">已核对结果，允许再次保存</button>
  </section>
  <section v-if="latest" class="latest-proposal" aria-label="最新计划独立预览"><h3>读取到的最新版本 {{ latest.version }}（独立预览）</h3><PlanSnapshotDetails :snapshot="latest" /><p>你仍需重新生成并确认，最新版本不会自动应用到建议。</p></section>
  <p v-if="status==='generating'" class="muted" role="status">正在根据描述生成建议。保存计划仍需你确认。</p>
  <section v-if="status==='needs_input'" class="proposal-result" aria-label="需要补充信息"><h3>还需要补充信息</h3><ul><li v-for="(question,index) in questionList" :key="index">{{ question }}</li></ul><p>你的原始描述已保留。补充后可重新生成。</p><button class="secondary-button" data-testid="cancel-proposal" type="button" @click="cancelProposal">取消建议</button></section>
  <section v-if="status==='unsupported'" class="proposal-result" aria-label="暂不支持的请求"><h3>暂时无法整理这项请求</h3><ul><li v-for="(question,index) in questionList" :key="index">{{ question }}</li></ul><p>你可以改为描述预约意向字段；建议不会执行预约、付款或创建任务。</p><button class="secondary-button" data-testid="cancel-proposal" type="button" @click="cancelProposal">关闭</button></section>
  <section v-if="proposal" class="proposal-result" aria-label="AI建议预览">
   <div class="proposal-heading"><h3>建议预览 · {{ proposal.kind==='unbound_draft'?'未绑定意向草案':'意向草案' }}</h3><span v-if="proposal.provider" class="proposal-provider">{{ proposal.provider.name }} · {{ proposal.provider.model }}</span></div>
   <p v-if="proposal.changes?.length" class="muted">逐项变更预览</p>
   <dl v-if="proposal.changes?.length" class="proposal-diff"><template v-for="(change,index) in proposal.changes" :key="`${change.field}-${index}`"><dt>{{ labels[change.field]||'其他意向字段' }}</dt><dd><span class="diff-before">{{ formatValue(change.field,change.before,proposal.context) }}</span><span aria-hidden="true"> → </span><strong>{{ formatValue(change.field,change.after,proposal.context) }}</strong></dd></template></dl>
   <p v-else class="muted">AI生成了完整预约意向草案。</p>
   <p v-if="proposal.context?.timezone_name" class="muted">业务时区：{{ proposal.context.timezone_name }}</p>
   <BookingWindowStatus v-if="proposal.booking_window" :state="proposal.booking_window" />
   <p class="proposal-safety">预约、付款、创建任务和上游查询均不可用。保存只会记录未绑定的人工意向。</p>
   <p v-if="targetChanged" class="proposal-feedback error" role="status">描述、目标计划或计划版本已变化。请重新生成后再保存。</p>
   <p v-if="needsRegeneration&&targetId" class="proposal-conflict-action"><button class="secondary-button" data-testid="read-latest-regenerate" type="button" :disabled="status==='generating'||busySaving" @click="readLatestAndRegenerate">读取最新并重新生成</button></p>
   <div class="proposal-actions"><button class="primary-button" data-testid="confirm-save-proposal" type="button" :disabled="!canSave" @click="saveProposal">{{ busySaving?'正在保存…':'确认并保存预约意向' }}</button><button class="secondary-button" data-testid="cancel-proposal" type="button" :disabled="busySaving||uncertainSave" @click="cancelProposal">取消建议</button></div>
  </section>
  <p v-if="needsRegeneration&&targetId&&!proposal" class="proposal-conflict-action"><button class="secondary-button" data-testid="read-latest-regenerate" type="button" :disabled="status==='generating'||busySaving" @click="readLatestAndRegenerate">读取最新并重新生成</button></p>
 </section>
</template>

<style scoped>
.proposal-assistant{display:grid;gap:18px;margin-bottom:22px}.proposal-heading{display:flex;align-items:center;justify-content:space-between;gap:14px;flex-wrap:wrap}.proposal-heading h2,.proposal-heading h3{margin:0}.proposal-heading h3{font-size:17px}.proposal-scope,.proposal-provider{color:var(--brand-dark);background:var(--brand-soft);padding:5px 10px;border-radius:999px;font-size:12px}.field textarea{width:100%;resize:vertical;border:1px solid #d5dfd7;border-radius:9px;padding:12px;background:var(--surface);color:var(--ink);font:inherit;line-height:1.6}.field textarea:focus-visible{outline:3px solid var(--brand);outline-offset:2px}.proposal-actions{display:flex;align-items:center;flex-wrap:wrap;gap:10px}.proposal-result,.verification-panel{padding:18px;border:1px solid var(--line);border-radius:12px;background:#fbfcfb}.proposal-result h3,.verification-panel h3{margin:0}.verification-panel{display:grid;gap:12px;border-color:var(--warning);background:var(--warning-soft)}.verification-panel p{margin:0}.proposal-result>p{margin:10px 0}.proposal-diff{display:grid;grid-template-columns:minmax(110px,1fr) minmax(0,3fr);gap:10px 16px}.proposal-diff dt{color:var(--muted)}.proposal-diff dd{margin:0;overflow-wrap:anywhere}.diff-before{color:var(--muted)}.proposal-safety{padding:12px;border-radius:9px;background:var(--brand-soft);color:var(--brand-dark)}.proposal-feedback{padding:12px 14px;margin:0;border-radius:10px}.proposal-feedback.error{background:var(--danger-soft);color:var(--danger)}.proposal-feedback.success{background:var(--brand-soft);color:var(--brand-dark)}.latest-proposal{margin:18px 0;padding:16px;border:1px solid var(--warning);border-radius:10px;background:var(--warning-soft)}.latest-proposal h4{margin:0}.latest-proposal p{margin-bottom:0}.proposal-conflict-action{margin:0!important}@media(max-width:600px){.proposal-diff{grid-template-columns:1fr;gap:4px}.proposal-diff dd{margin-bottom:10px}}
</style>
