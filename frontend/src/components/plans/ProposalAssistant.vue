<script setup>
import { computed, onBeforeUnmount, ref, shallowRef, watch } from 'vue';
import { RouterLink } from 'vue-router';
import AppIcon from '../AppIcon.vue';
import PlanSnapshotDetails from './PlanSnapshotDetails.vue';
import BookingWindowStatus from './BookingWindowStatus.vue';
import AgentCredentialGate from './AgentCredentialGate.vue';
import ProposalConversationHistory from './ProposalConversationHistory.vue';
import ProposalComposer from './ProposalComposer.vue';
import ProposalModePicker from './ProposalModePicker.vue';
import { providerErrorMessage } from '../../api/providerErrors.js';

const props=defineProps({plans:{type:Array,default:()=>[]},planApi:{type:Object,required:true},proposalApi:{type:Object,required:true},credentialApi:{type:Object,default:null},credentialRefreshKey:{type:Number,default:0},session:{type:Object,required:true},credentialId:{type:String,default:''}});
const emit=defineEmits(['saved','refresh-request']);
const message=shallowRef(''),targetId=shallowRef(''),mode=shallowRef('new'),proposal=shallowRef(null),status=shallowRef('idle');
const questions=ref([]),error=shallowRef(''),savedNotice=shallowRef(''),latest=shallowRef(null),latestError=shallowRef('');
const generatedFor=shallowRef(null),busySaving=shallowRef(false),needsRegeneration=shallowRef(false);
const uncertainSave=shallowRef(false),verificationLoading=shallowRef(false),verificationComplete=shallowRef(false),verificationResult=shallowRef(null);
const ownSavedVersion=shallowRef(null);
const answers=ref([]),answer=shallowRef(''),conversationBase=shallowRef(null),questionHistory=ref([]),trace=ref([]),pendingTurn=shallowRef(''),credentialReady=shallowRef(false);
const labels={target_date:'目标日期',preferred_start_times:'开始时间偏好',duration_minutes:'预约时长',venue_preference:'场馆偏好',court_preferences:'场地偏好',fallback_policy:'备用策略',price_ceiling_minor:'价格上限'};
const currentTarget=computed(()=>targetId.value||null);
const selectedPlan=computed(()=>props.plans.find(plan=>plan.plan_id===targetId.value)||null);
const targetChanged=computed(()=>Boolean(generatedFor.value)&&(
 generatedFor.value.planId!==currentTarget.value
 || (currentTarget.value&&selectedPlan.value&&generatedFor.value.listVersion!==selectedPlan.value.version)
 || generatedFor.value.message!==message.value.trim()
));
const canSave=computed(()=>status.value==='ready'&&proposal.value?.can_book===false&&intentComplete.value&&canStart.value&&generatedFor.value&&(generatedFor.value.planId||generatedFor.value.credentialId)&&!targetChanged.value&&!needsRegeneration.value&&!uncertainSave.value&&!busySaving.value);
const questionList=computed(()=>Array.isArray(questions.value)?questions.value:[]);
function validCalendarDate(value){
 if(typeof value!=='string'||!/^\d{4}-\d{2}-\d{2}$/.test(value))return false;
 const [year,month,day]=value.split('-').map(Number),candidate=new Date(Date.UTC(year,month-1,day));
 return candidate.getUTCFullYear()===year&&candidate.getUTCMonth()===month-1&&candidate.getUTCDate()===day;
}
function minuteOfDay(value){return typeof value==='string'&&/^([01]\d|2[0-3]):[0-5]\d$/.test(value)?Number(value.slice(0,2))*60+Number(value.slice(3)):null;}
const intentValidationError=computed(()=>{
 const intent=proposal.value?.intent,fallback=intent?.fallback_policy,times=intent?.preferred_start_times,duration=intent?.duration_minutes;
 if(!validCalendarDate(intent?.target_date))return '预约日期无效，请选择一个真实存在的日期。';
 const businessDate=proposal.value?.booking_window?.business_date;
 if(validCalendarDate(businessDate)&&intent.target_date<businessDate)return `预约日期已过（当前业务日期：${businessDate}），请选择未来日期。`;
 if(!Array.isArray(times)||times.length<1||times.length>8||new Set(times).size!==times.length)return '请按优先顺序填写1～8个不同的开始时间。';
 if(!times.every(value=>minuteOfDay(value)!==null))return '开始时间格式无效，请使用24小时制HH:MM。';
 if(!Number.isInteger(duration)||duration<30||duration>240||duration%30!==0)return '预约时长须为30～240分钟，以30分钟递增。';
 if(times.some(value=>minuteOfDay(value)<540||minuteOfDay(value)+duration>1320)){
  const latest=22*60-duration;
  return `预约时段为09:00–22:00；${duration}分钟必须在22:00前结束（最晚${String(Math.floor(latest/60)).padStart(2,'0')}:${String(latest%60).padStart(2,'0')}开始）。`;
 }
 if(typeof intent?.venue_preference!=='string'||!intent.venue_preference.trim())return '请确认场馆名称或描述。';
 if(!Array.isArray(intent.court_preferences)||intent.court_preferences.length>16||new Set(intent.court_preferences).size!==intent.court_preferences.length)return '请检查场地偏好，不能重复且最多16项。';
 if(intent.court_preferences.some(value=>typeof value!=='string'||!/^(?:[1-9]|10)号场$/.test(value)))return '场地编号仅支持1～10号场，例如“6号场”。';
 if(typeof fallback?.allow_any_court_in_venue!=='boolean'||typeof fallback?.allow_time_shift!=='boolean')return '请明确同场馆备用和时间浮动设置。';
 if(intent.court_preferences.length===0&&fallback.allow_any_court_in_venue!==true)return '请填写1～10号场的偏好，或明确允许同场馆其他场地。';
 if(!fallback.allow_time_shift&&fallback.allowed_start_time_range!==null)return '未允许时间浮动时，浮动范围必须为空。';
 if(fallback.allow_time_shift){
  const range=fallback.allowed_start_time_range,start=minuteOfDay(range?.start),end=minuteOfDay(range?.end);
  if(start===null||end===null||start>end||start<540||end+duration>1320||times.some(value=>minuteOfDay(value)<start||minuteOfDay(value)>end))return '时间浮动范围必须覆盖首选时间，并保证预约在09:00–22:00内完成。';
 }
 if(intent.price_ceiling_minor!==null&&(!Number.isSafeInteger(intent.price_ceiling_minor)||intent.price_ceiling_minor<0))return '价格上限无效。';
 return '';
});
const intentComplete=computed(()=>!intentValidationError.value);
const canStart= computed(()=>!props.credentialApi||credentialReady.value);
const followUpActive=computed(()=>questionList.value.length>0&&!proposal.value&&status.value!=='unsupported');
let alive=true,epoch=0,requestId=0;
const authorized=()=>props.session.status==='authenticated'&&Boolean(props.session.user?.user_id);
function valid(generation,userId,csrfToken){return alive&&generation===epoch&&authorized()&&props.session.user?.user_id===userId&&props.session.csrfToken===csrfToken;}
function resetForSession(values,previous){
 epoch++;requestId++;proposal.value=null;generatedFor.value=null;status.value='idle';questions.value=[];latest.value=null;latestError.value='';error.value='';savedNotice.value='';needsRegeneration.value=false;uncertainSave.value=false;verificationLoading.value=false;verificationComplete.value=false;verificationResult.value=null;ownSavedVersion.value=null;busySaving.value=false;answers.value=[];questionHistory.value=[];answer.value='';conversationBase.value=null;trace.value=[];pendingTurn.value='';credentialReady.value=!props.credentialApi;
 if(previous&&(previous[1]!==values[1]||previous[3]!==values[3]||values[0]!=='authenticated')){message.value='';targetId.value='';mode.value='new';}
}
watch(()=>[props.session.status,props.session.user?.user_id,props.session.csrfToken,props.credentialId],resetForSession,{flush:'sync'});
watch(()=>[message.value,targetId.value,selectedPlan.value?.version,mode.value],(current,previous)=>{
 requestId++;
 if(status.value==='generating')status.value='idle';
 const modeOrTargetChanged=current[1]!==previous[1]||current[3]!==previous[3];
 const inputOrTargetChanged=current[0]!==previous[0]||modeOrTargetChanged;
 if(inputOrTargetChanged){
  const targetSwitch=modeOrTargetChanged&&conversationBase.value;
  answers.value=[];questionHistory.value=[];answer.value='';conversationBase.value=null;questions.value=[];
  if(targetSwitch){message.value='';clearProposal();trace.value=[];}
  savedNotice.value='';ownSavedVersion.value=null;return;}
 const versionChanged=current[2]!==previous[2];
 if(versionChanged){
  const ownUpdate=ownSavedVersion.value&&current[1]===ownSavedVersion.value.planId&&current[2]===ownSavedVersion.value.version;
  if(ownUpdate)ownSavedVersion.value=null;
  else{savedNotice.value='';ownSavedVersion.value=null;if(conversationBase.value?.planId===current[1])needsRegeneration.value=true;}
 }
},{flush:'sync'});
function traceEvent(title,detail){
 const time=new Intl.DateTimeFormat('zh-CN',{hour:'2-digit',minute:'2-digit'}).format(new Date());
 trace.value=[...trace.value,{id:`${Date.now()}-${trace.value.length}`,title,detail,time}];
}
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
function restartConversation(){if(busySaving.value||uncertainSave.value)return;requestId++;clearProposal();answers.value=[];questionHistory.value=[];answer.value='';conversationBase.value=null;message.value='';trace.value=[];pendingTurn.value='';}
function selectMode(next){if(next!=='new'&&next!=='edit')return;mode.value=next;if(next==='new')targetId.value='';}
async function generate({forceLatest=false,latestPlan=null,supplement=false}={}){
 if(!authorized()||!canStart.value||status.value==='generating'||busySaving.value||uncertainSave.value||!message.value.trim()||(mode.value==='edit'&&!targetId.value)||(needsRegeneration.value&&!forceLatest))return;
 const nextQuestions=supplement?[...questionHistory.value,[...questionList.value]]:[...questionHistory.value];
 const nextAnswers=supplement?[...answers.value,answer.value.trim()]:[...answers.value];
 if(supplement&&(!answer.value.trim()||nextAnswers.length>7))return;
 const generation=epoch,id=props.session.user.user_id,csrf=props.session.csrfToken,sequence=++requestId,selectedId=targetId.value||null,userMessage=message.value.trim(),listVersion=selectedPlan.value?.version??null;
 status.value='generating';error.value='';savedNotice.value='';latestError.value='';proposal.value=null;generatedFor.value=null;needsRegeneration.value=false;uncertainSave.value=false;verificationComplete.value=false;verificationResult.value=null;
 pendingTurn.value=supplement?answer.value.trim():'';
 if(!supplement||trace.value.length===0)trace.value=[];
 traceEvent(supplement?'提交补充回答':'提交预约需求',supplement?'继续核对必需信息。':'开始整理日期、时段、场馆和场地偏好。');
 try{
  let plan=latestPlan;
  if(selectedId&&!conversationBase.value&&!plan){const scope=selectedPlan.value?.credential_id;const response=scope?await props.planApi.get(selectedId,scope):await props.planApi.get(selectedId);if(!valid(generation,id,csrf)||sequence!==requestId)return;plan=response.plan;traceEvent('读取计划版本',`读取到版本 ${plan.version}，将以此版本为修改基准。`);}
  if(!conversationBase.value||forceLatest)conversationBase.value={planId:selectedId,version:plan?.version??null};
  if(forceLatest&&plan)latest.value=plan;
  const baseVersion=conversationBase.value.version;
  const scopedCredentialId=selectedId?(plan?.credential_id||selectedPlan.value?.credential_id||null):(props.credentialId||null);
  const result=scopedCredentialId
   ? (nextAnswers.length?await props.proposalApi.generate(userMessage,selectedId,baseVersion,nextAnswers,nextQuestions,scopedCredentialId):await props.proposalApi.generate(userMessage,selectedId,baseVersion,undefined,undefined,scopedCredentialId))
   : (nextAnswers.length?await props.proposalApi.generate(userMessage,selectedId,baseVersion,nextAnswers,nextQuestions):await props.proposalApi.generate(userMessage,selectedId,baseVersion));
  if(!valid(generation,id,csrf)||sequence!==requestId)return;
  answers.value=nextAnswers;questionHistory.value=nextQuestions;if(supplement)answer.value='';pendingTurn.value='';
  proposal.value=result.proposal;questions.value=result.status==='needs_input'?(result.questions||[]).slice(0,1):(result.questions||[]);status.value=result.status;
  generatedFor.value={message:userMessage,planId:selectedId,credentialId:scopedCredentialId,baseVersion:result.proposal?.base_version??baseVersion,listVersion};
  if(result.status==='needs_input')traceEvent('必需信息尚未齐全','我先确认一项优先信息；答复后继续检查其他缺口。当前没有生成或保存计划。');
  else if(result.status==='ready')traceEvent('预约意向草案已生成',intentComplete.value?'必填字段完整；等待你核对并确认保存。':'草案字段未通过完整性检查，保存已禁用。');
  else traceEvent('请求不属于整理范围','未生成预约意向；助手不会代为查询、预约、付款或创建任务。');
  if(forceLatest&&plan)latest.value=plan;
 }catch(err){
  if(!valid(generation,id,csrf)||sequence!==requestId)return;
  pendingTurn.value='';traceEvent('模型请求未完成','请查看错误提示并修正配置或重试；没有保存预约意向。');
  status.value='error';error.value=err?.code==='provider_not_configured'?'尚未配置 AI 模型，请先完成设置。':err?.code==='provider_api_key_required'?'当前模型缺少 API Key，请前往模型设置补充密钥。':err?.code==='plan_version_conflict'?'计划版本已变化。你的描述仍保留，请读取最新版本并重新生成。':`生成建议失败：${providerErrorMessage(err?.code)}`;
  if(err?.code==='plan_version_conflict')needsRegeneration.value=true;
 }finally{if(valid(generation,id,csrf)&&sequence===requestId&&status.value==='generating')status.value='idle';}
}
async function readLatestAndRegenerate(){
 if(!targetId.value||!authorized()||busySaving.value)return;
 const generation=epoch,id=props.session.user.user_id,csrf=props.session.csrfToken,sequence=requestId,selected=targetId.value,capturedMessage=message.value.trim();
 latest.value=null;latestError.value='';error.value='';needsRegeneration.value=true;
 try{const scope=selectedPlan.value?.credential_id;const result=scope?await props.planApi.get(selected,scope):await props.planApi.get(selected);if(!valid(generation,id,csrf)||sequence!==requestId||selected!==targetId.value||capturedMessage!==message.value.trim())return;latest.value=result.plan;await generate({forceLatest:true,latestPlan:result.plan,supplement:Boolean(answer.value.trim())});}
 catch{if(valid(generation,id,csrf))latestError.value='最新版本读取失败，描述和当前建议仍保留。请重试。';}
}
async function saveProposal(){
 if(!canSave.value)return;const generation=epoch,id=props.session.user.user_id,csrf=props.session.csrfToken,captured=generatedFor.value;
 busySaving.value=true;error.value='';savedNotice.value='';traceEvent('你确认保存预约意向','已提交计划保存请求；不会在此步骤预约或付款。');
 try{
  const result=captured.planId
   ? (captured.credentialId?await props.planApi.update(captured.planId,captured.baseVersion,proposal.value.intent,captured.credentialId):await props.planApi.update(captured.planId,captured.baseVersion,proposal.value.intent))
   : (captured.credentialId?await props.planApi.create(proposal.value.intent,captured.credentialId):await props.planApi.create(proposal.value.intent));
  if(!valid(generation,id,csrf))return;
  savedNotice.value=`预约意向已保存 · 版本 ${result.plan.version}`;traceEvent('预约意向保存成功',`已保存为版本 ${result.plan.version}。`);ownSavedVersion.value=captured.planId?{planId:captured.planId,version:result.plan.version}:null;proposal.value=null;generatedFor.value=null;status.value='saved';needsRegeneration.value=false;conversationBase.value=null;answers.value=[];questionHistory.value=[];answer.value='';emit('saved',result.plan);emit('refresh-request');
 }catch(err){
  if(!valid(generation,id,csrf))return;
  if(err?.code==='plan_version_conflict'){error.value='保存时检测到版本冲突。你的描述和建议均已保留。';traceEvent('版本冲突','计划已被更新；请读取最新版本并重新生成。');needsRegeneration.value=true;}
  else if(err?.code==='provider_api_key_required'||err?.code==='provider_not_configured')error.value='当前模型缺少可用 API Key，请前往模型设置补充密钥后再重新生成。';
  else if(err?.status===400)error.value='预约意向未保存，请检查字段后重试；当前建议仍保留。';
  else if(err?.kind==='network'||err?.kind==='timeout'||!err?.status||err.status>=500){uncertainSave.value=true;verificationComplete.value=false;verificationResult.value=null;latest.value=null;latestError.value='';error.value='保存结果暂时无法确认。请先读取计划列表或最新版本，核对后再决定是否重试。';traceEvent('保存结果待核对','连接中断，尚不能确定服务端是否完成保存。');}
  else {error.value='预约意向保存失败，当前建议仍保留。请检查错误后再试。';traceEvent('预约意向保存失败','服务端未确认保存成功；当前建议仍保留。');}
 }finally{if(valid(generation,id,csrf))busySaving.value=false;}
}
async function verifyAmbiguousSave(){
 if(!uncertainSave.value||verificationLoading.value||!authorized())return;
 const generation=epoch,id=props.session.user.user_id,csrf=props.session.csrfToken,sequence=++requestId,selected=generatedFor.value?.planId||null;
 verificationLoading.value=true;verificationComplete.value=false;verificationResult.value=null;latestError.value='';
 try{
  if(selected){const scope=generatedFor.value?.credentialId??props.credentialId;const response=scope?await props.planApi.get(selected,scope):await props.planApi.get(selected);if(!valid(generation,id,csrf)||sequence!==requestId)return;verificationResult.value={type:'plan',plan:response.plan};latest.value=response.plan;}
  else{const response=props.credentialId?await props.planApi.list(props.credentialId):await props.planApi.list();if(!valid(generation,id,csrf)||sequence!==requestId)return;verificationResult.value={type:'list',plans:response.plans||[]};}
  verificationComplete.value=true;
 }catch{if(valid(generation,id,csrf)&&sequence===requestId)latestError.value='核对读取失败，描述和建议已保留；请重试读取。';}
 finally{if(valid(generation,id,csrf)&&sequence===requestId)verificationLoading.value=false;}
}
function acknowledgeAmbiguousSave(){if(uncertainSave.value&&verificationComplete.value){uncertainSave.value=false;error.value='';savedNotice.value='核对已完成。如仍需保存，请再次确认。';}}
function cancelProposal(){clearProposal();}
onBeforeUnmount(()=>{alive=false;epoch++;requestId++;});
</script>

<template>
 <section class="proposal-assistant" aria-label="AI预约助手">
  <ProposalConversationHistory :message="message" :answers="answers" :question-history="questionHistory" :questions="questionList" :pending-turn="pendingTurn" :status="status" :error="error" :saved-notice="savedNotice" :trace="trace" :show-credential-status="Boolean(credentialApi)" @restart="restartConversation">
   <template #header-actions><slot name="header-actions" /></template>
   <template #system-message><AgentCredentialGate v-if="credentialApi" :api="credentialApi" :session="session" :credential-id="credentialId" :refresh-key="credentialRefreshKey" @ready-change="credentialReady=$event" /></template>
   <template #welcome-actions><ProposalModePicker :mode="mode" :disabled="status==='generating'||busySaving||uncertainSave" @update:mode="selectMode" /></template>
   <template #conversation-extra>
    <li v-if="latestError" class="chat-row is-assistant"><div class="chat-bubble bubble-error" role="alert">{{ latestError }}</div></li>
    <li v-if="uncertainSave" class="chat-row is-assistant"><div class="chat-bubble bubble-artifact">
     <section class="verification-panel" aria-label="保存结果核对">
      <h3>保存结果待核对</h3><p>为避免重复创建，请先读取列表或该计划最新版本。核对结果后，明确确认才会重新允许保存。</p>
      <button class="secondary-button" data-testid="verify-ambiguous-save" type="button" :disabled="verificationLoading" @click="verifyAmbiguousSave">{{ verificationLoading?'正在读取…':generatedFor?.planId?'读取最新版本':'读取计划列表' }}</button>
      <p v-if="verificationResult?.type==='list'" role="status">已读取计划列表，共 {{ verificationResult.plans.length }} 个预约计划。</p>
      <ul v-if="verificationResult?.type==='list'&&verificationResult.plans.length"><li v-for="plan in verificationResult.plans.slice(0,5)" :key="plan.plan_id">{{ plan.intent.venue_preference }} · {{ plan.intent.target_date }} · 版本 {{ plan.version }}</li></ul>
      <button class="primary-button" data-testid="acknowledge-save-check" type="button" :disabled="!verificationComplete" @click="acknowledgeAmbiguousSave">已核对结果，允许再次保存</button>
     </section>
    </div></li>
    <li v-if="latest" class="chat-row is-assistant"><div class="chat-bubble bubble-artifact">
     <section class="latest-proposal" aria-label="最新计划独立预览"><h3>读取到的最新版本 {{ latest.version }}</h3><PlanSnapshotDetails :snapshot="latest" /><p>请重新生成并确认；最新版本不会自动应用到建议。</p></section>
    </div></li>
    <li v-if="status==='needs_input'" class="chat-row is-assistant"><div class="chat-bubble"><button class="secondary-button" data-testid="cancel-proposal" type="button" @click="cancelProposal">取消本轮整理</button></div></li>
    <li v-if="needsRegeneration&&targetId&&!proposal" class="chat-row is-assistant"><div class="chat-bubble"><button class="secondary-button" data-testid="read-latest-regenerate" type="button" :disabled="status==='generating'||busySaving" @click="readLatestAndRegenerate">读取最新并重新生成</button></div></li>
    <li v-if="proposal" class="chat-row is-assistant"><div class="chat-bubble bubble-artifact">
     <section class="proposal-result" aria-label="AI建议预览">
      <div class="proposal-result-heading"><div><span class="eyebrow">建议预览</span><h3>{{ proposal.kind==='unbound_draft'?'未绑定意向草案':'预约意向草案' }}</h3></div><span v-if="proposal.provider" class="proposal-provider">{{ proposal.provider.name }} · {{ proposal.provider.model }}</span></div>
      <p v-if="proposal.changes?.length" class="muted">逐项核对变更</p>
      <dl v-if="proposal.changes?.length" class="proposal-diff"><template v-for="(change,index) in proposal.changes" :key="`${change.field}-${index}`"><dt>{{ labels[change.field]||'其他意向字段' }}</dt><dd><span class="diff-before">{{ formatValue(change.field,change.before,proposal.context) }}</span><span aria-hidden="true"> → </span><strong>{{ formatValue(change.field,change.after,proposal.context) }}</strong></dd></template></dl>
      <p v-else class="muted">已整理出完整预约意向草案。</p>
      <p v-if="!intentComplete" class="proposal-feedback error" role="alert">{{ intentValidationError }}</p>
      <p v-if="proposal.context?.timezone_name" class="muted">业务时区：{{ proposal.context.timezone_name }}</p>
      <BookingWindowStatus v-if="proposal.booking_window" :state="proposal.booking_window" />
      <p class="proposal-safety" data-testid="proposal-quality-note">草案已通过日期、时长、场馆、场地偏好和原文依据校验；请核对预览后确认保存。本步骤只保存意向，不会立即预约或付款。</p>
      <p v-if="targetChanged" class="proposal-feedback error" role="status">描述、目标计划或计划版本已变化。请重新生成后再保存。</p>
      <p v-if="needsRegeneration&&targetId" class="proposal-conflict-action"><button class="secondary-button" data-testid="read-latest-regenerate" type="button" :disabled="status==='generating'||busySaving" @click="readLatestAndRegenerate">读取最新并重新生成</button></p>
      <div class="proposal-actions"><button class="primary-button" data-testid="confirm-save-proposal" type="button" :disabled="!canSave" @click="saveProposal">{{ busySaving?'正在保存…':'确认并保存预约意向' }}</button><button class="secondary-button" data-testid="cancel-proposal" type="button" :disabled="busySaving||uncertainSave" @click="cancelProposal">取消建议</button></div>
     </section>
    </div></li>
   </template>
   <template #composer>
    <ProposalComposer :message="message" :answer="answer" :mode="mode" :target-id="targetId" :plans="plans" :status="status" :follow-up="followUpActive" :busy="status==='generating'||busySaving" :blocked="!canStart||needsRegeneration" :locked="uncertainSave" :selection-disabled="busySaving||uncertainSave" @update:message="message=$event" @update:answer="answer=$event" @update:target-id="targetId=$event" @send="supplement=>generate({supplement})" />
   </template>
  </ProposalConversationHistory>
 </section>
</template>

<style scoped>
.proposal-assistant{min-width:0;margin-bottom:22px}.proposal-result,.verification-panel{display:grid;gap:12px;padding:14px;border:1px solid var(--line);border-radius:12px;background:var(--surface)}.proposal-result h3,.verification-panel h3{margin:0}.proposal-result p,.verification-panel p{margin:0}.verification-panel{border-color:var(--warning);background:var(--warning-soft)}.proposal-result-heading{display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:10px}.proposal-result-heading h3{margin-top:2px;font-size:16px}.proposal-provider{color:var(--brand-dark);background:var(--brand-soft);padding:5px 10px;border-radius:999px;font-size:11px}.proposal-actions{display:flex;align-items:center;flex-wrap:wrap;gap:8px;padding-top:4px}.proposal-actions button,.verification-panel button{min-height:44px}.proposal-diff{display:grid;grid-template-columns:minmax(100px,1fr) minmax(0,3fr);gap:8px 14px;margin:0}.proposal-diff dt{color:var(--muted);font-size:12px}.proposal-diff dd{margin:0;overflow-wrap:anywhere;font-size:13px}.diff-before{color:var(--muted)}.proposal-safety{padding:9px 11px;border-radius:9px;background:var(--brand-soft);color:var(--brand-dark);font-size:12px}.proposal-feedback{padding:10px 12px;margin:0;border-radius:9px}.proposal-feedback.error{background:var(--danger-soft);color:var(--danger)}.proposal-feedback.success{background:var(--brand-soft);color:var(--brand-dark)}.latest-proposal{display:grid;gap:10px;margin:0;padding:12px;border:1px solid var(--warning);border-radius:10px;background:var(--warning-soft)}.latest-proposal h3{font-size:14px}.latest-proposal p{margin:0;color:var(--muted);font-size:12px}.proposal-conflict-action{margin:0!important}.proposal-assistant :deep(button:focus-visible){outline:3px solid var(--brand);outline-offset:2px}@media(max-width:600px){.proposal-diff{grid-template-columns:1fr;gap:3px}.proposal-diff dd{margin-bottom:6px}.proposal-result,.verification-panel{padding:12px}.proposal-actions{display:grid;grid-template-columns:1fr}.proposal-actions button{width:100%}}
</style>
