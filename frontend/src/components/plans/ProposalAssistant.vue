<script setup>
import { computed, onBeforeUnmount, onMounted, ref, shallowRef, watch } from 'vue';
import AgentCredentialGate from './AgentCredentialGate.vue';
import ProposalConversationHistory from './ProposalConversationHistory.vue';
import ProposalComposer from './ProposalComposer.vue';
import ProposalQueuePreview from './ProposalQueuePreview.vue';
import { providerErrorMessage } from '../../api/providerErrors.js';
import { initialState, isLegal, legacyStatus, selectors, transition } from './proposalMachine.js';

const props=defineProps({planApi:{type:Object,required:true},proposalApi:{type:Object,required:true},credentialApi:{type:Object,default:null},credentialRefreshKey:{type:Number,default:0},session:{type:Object,required:true},credentialId:{type:String,default:''},scopeLabel:{type:String,default:''}});
const emit=defineEmits(['saved','refresh-request','manual-request','mode-started','mode-reset','provider-unavailable']);
const MAX_ANSWERS=20,HOURS={120:'2小时',60:'1小时'};
const machine=shallowRef(initialState());
function dispatch(type,extra={}){machine.value=transition(machine.value,{type,...extra});}
const status=computed(()=>legacyStatus(machine.value)),busySaving=computed(()=>selectors.saving(machine.value)),stale=computed(()=>selectors.stale(machine.value)),escalated=computed(()=>selectors.escalated(machine.value));
const busyConversation=ref(false);
const message=shallowRef(''),proposal=shallowRef(null),generatedFor=shallowRef(null);
const answers=ref([]),answer=shallowRef(''),questionHistory=ref([]),replyHistory=ref([]),askedFields=ref([]),roundHeadings=ref([]),questions=ref([]);
const conversationId=shallowRef(''),conversations=ref([]),contextualReply=shallowRef('');
const error=shallowRef(''),savedNotice=shallowRef(''),trace=ref([]),pendingTurn=shallowRef(''),credentialReady=shallowRef(false);
const pendingMessage=shallowRef(''),resetNotice=shallowRef(false),editingOriginal=shallowRef(false);
const view=computed(()=>machine.value.conversation),questionList=computed(()=>Array.isArray(questions.value)?questions.value:[]);
const canStart=computed(()=>!props.credentialApi||credentialReady.value);
const targetChanged=computed(()=>Boolean(generatedFor.value)&&generatedFor.value.message!==message.value.trim());
const scopeChanged=computed(()=>Boolean(generatedFor.value)&&generatedFor.value.scopeLabel!==props.scopeLabel);
const entries=computed(()=>proposal.value?.entries||[]);
const canSave=computed(()=>status.value==='ready'&&proposal.value?.can_book===false&&entries.value.length>0&&canStart.value&&Boolean(generatedFor.value)&&Boolean(props.scopeLabel)&&!targetChanged.value&&!scopeChanged.value&&!resetNotice.value&&!editingOriginal.value&&!stale.value&&!busySaving.value&&!busyConversation.value);
const followUpActive=computed(()=>questionList.value.length>0&&!proposal.value&&status.value!=='unsupported');
const notices=computed(()=>status.value==='idle'?[]:view.value?.notices||[]);
const warnings=computed(()=>proposal.value?.warnings||[]);
const scheduleClass=computed(()=>proposal.value?.schedule?.state==='scheduled'?'is-ok':'is-warn');
let alive=true,epoch=0,requestId=0,restoreSequence=0,restoreRequest=null;
const authorized=()=>props.session.status==='authenticated'&&Boolean(props.session.user?.user_id);
function valid(generation,userId,csrfToken){return alive&&generation===epoch&&authorized()&&props.session.user?.user_id===userId&&props.session.csrfToken===csrfToken;}
function dateText(iso){return /^\d{4}-\d{2}-\d{2}$/.test(iso||'')?`${iso.slice(0,4)}年${iso.slice(5,7)}月${iso.slice(8,10)}日`:'';}
function entryText(entry){return `${HOURS[entry.duration_minutes]||''} ${entry.start_time}-${entry.end_time} ${entry.court_preference}`;}
const modeChoices=[{value:'1',label:'1 / A',description:'只抢2小时'},{value:'2',label:'2 / B',description:'只抢1小时'},{value:'3',label:'3 / C',description:'两种都抢，分开确认'}];
function clearConversation(){answers.value=[];questionHistory.value=[];replyHistory.value=[];askedFields.value=[];roundHeadings.value=[];answer.value='';questions.value=[];contextualReply.value='';}
function traceEvent(title,detail){
 const time=new Intl.DateTimeFormat('zh-CN',{hour:'2-digit',minute:'2-digit'}).format(new Date());
 trace.value=[...trace.value,{id:`${Date.now()}-${trace.value.length}`,title,detail,time}];
}
function resetForSession(values,previous){
 epoch++;requestId++;restoreSequence++;conversationId.value='';conversations.value=[];machine.value=initialState();proposal.value=null;generatedFor.value=null;clearConversation();error.value='';savedNotice.value='';trace.value=[];pendingTurn.value='';pendingMessage.value='';resetNotice.value=false;editingOriginal.value=false;credentialReady.value=!props.credentialApi;
 if(previous&&(previous[1]!==values[1]||previous[3]!==values[3]||values[0]!=='authenticated'))message.value='';
 emit('mode-reset');
}
async function restoreConversation(){
 const sequence=++restoreSequence,credentialId=props.credentialId;
 if(!authorized()||!credentialId||typeof props.proposalApi.restore!=='function')return;
 const generation=epoch,userId=props.session.user.user_id,csrfToken=props.session.csrfToken;
 let pending=null;
 try{
  pending={credentialId,userId,csrfToken,promise:props.proposalApi.restore(credentialId)};restoreRequest=pending;
  const snapshot=await pending.promise;
  if(sequence!==restoreSequence||!valid(generation,userId,csrfToken))return;
  conversations.value=snapshot?.conversations||[];
  const saved=snapshot?.conversation;
  if(!saved)return;
  hydrateConversation(saved);
 }catch{
  if(sequence===restoreSequence&&valid(generation,userId,csrfToken))error.value='已保存的对话暂时无法恢复，请重新读取或开始新对话。';
 }finally{
  if(restoreRequest===pending)restoreRequest=null;
 }
}
function hydrateConversation(saved){
  const history=saved.response_history,answersSaved=saved.answers;
  if(typeof saved.message!=='string'||!Array.isArray(answersSaved)||!Array.isArray(saved.asked_fields)
     ||!Array.isArray(history)||history.length!==answersSaved.length+1)return;
  conversationId.value=saved.conversation_id;message.value=saved.message;answers.value=answersSaved;
  askedFields.value=saved.asked_fields;questionHistory.value=history.slice(0,answersSaved.length).map(item=>item.questions||[]);
  replyHistory.value=history.slice(0,answersSaved.length).map(item=>item.conversation?.contextual_reply||'');
  roundHeadings.value=history.slice(0,answersSaved.length).map(item=>item.conversation?.heading||'');
  trace.value=history.flatMap((item,index)=>{
   const event=item.trace_event||{},time=Number.isSafeInteger(event.at_utc_ms)?new Intl.DateTimeFormat('zh-CN',{hour:'2-digit',minute:'2-digit'}).format(new Date(event.at_utc_ms)):'';
   return [
    {id:`restored-${index}-user`,title:event.submitted_title||(index?'提交补充回答':'提交预约需求'),detail:event.submitted_detail||'已从服务端恢复。',time},
    {id:`restored-${index}-assistant`,title:event.result_title||'对话结果已恢复',detail:event.result_detail||'已从服务端恢复。',time},
   ];
  });
  const last=history.at(-1);proposal.value=last.proposal||null;
  contextualReply.value=last.conversation?.contextual_reply||'';
  questions.value=last.status==='needs_input'?(last.questions||[]).slice(0,1):(last.questions||[]);
  dispatch('SEND');
  applyAnswer(last.status,last.conversation||null,Boolean(last.conversation?.escalation));
  generatedFor.value={message:saved.message,credentialId:props.credentialId,scopeLabel:saved.scope_label};
}
async function refreshConversationHistory(){
 if(!authorized()||!props.credentialId||typeof props.proposalApi.restore!=='function')return;
 try{conversations.value=(await props.proposalApi.restore(props.credentialId))?.conversations||[];}catch{}
}
watch(()=>[props.session.status,props.session.user?.user_id,props.session.csrfToken,props.credentialId],(values,previous)=>{resetForSession(values,previous);void restoreConversation();},{flush:'sync'});
onMounted(()=>restoreConversation());
watch(message,()=>{requestId++;if(status.value==='generating')dispatch('INPUT_CHANGED');clearConversation();savedNotice.value='';},{flush:'sync'});
async function closeCurrentConversation(){
 restoreSequence++;
 const id=conversationId.value;
 let conversationIdToClose=id;
 const pending=restoreRequest;
 if(!conversationIdToClose&&pending?.credentialId===props.credentialId&&pending.userId===props.session.user?.user_id&&pending.csrfToken===props.session.csrfToken){
  try{conversationIdToClose=(await pending.promise)?.conversation?.conversation_id||'';}
  catch{error.value='对话未能归档到历史记录，请重试。';return false;}
 }
 if(!conversationIdToClose||typeof props.proposalApi.close!=='function'||!props.credentialId)return true;
 try{
  await props.proposalApi.close(conversationIdToClose,props.credentialId);
  if(conversationId.value===conversationIdToClose)conversationId.value='';
  await refreshConversationHistory();
  return true;
 }catch{error.value='对话未能归档到历史记录，请重试。';return false;}
}
function onMessageInput(next){
 if(answers.value.length&&next!==message.value){pendingMessage.value=next;resetNotice.value=true;return;}
 if(next!==message.value&&(conversationId.value||restoreRequest))void closeCurrentConversation();
 editingOriginal.value=false;message.value=next;
}
function applyMessageReset(){void closeCurrentConversation();const next=pendingMessage.value;resetNotice.value=false;pendingMessage.value='';editingOriginal.value=false;message.value=next;}
function cancelMessageReset(){resetNotice.value=false;pendingMessage.value='';editingOriginal.value=false;}
function clearProposal(){dispatch('RESTART');proposal.value=null;questions.value=[];generatedFor.value=null;error.value='';savedNotice.value='';}
async function restartConversation(){if(busyConversation.value||busySaving.value||status.value==='generating')return;busyConversation.value=true;try{if(!await closeCurrentConversation())return;requestId++;clearProposal();clearConversation();message.value='';trace.value=[];pendingTurn.value='';pendingMessage.value='';resetNotice.value=false;editingOriginal.value=false;await refreshConversationHistory();emit('mode-reset');}finally{busyConversation.value=false;}}
async function cancelProposal(){if(busyConversation.value||status.value==='generating')return;busyConversation.value=true;try{if(!await closeCurrentConversation())return;clearProposal();clearConversation();message.value='';emit('mode-reset');}finally{busyConversation.value=false;}}
async function selectConversation(id){
 if(!id||id===conversationId.value||busyConversation.value||busySaving.value||status.value==='generating'||typeof props.proposalApi.resume!=='function')return;
 const generation=epoch,userId=props.session.user.user_id,csrf=props.session.csrfToken;
 busyConversation.value=true;error.value='';pendingTurn.value='';
 try{
  const result=await props.proposalApi.resume(id,props.credentialId);
  if(!valid(generation,userId,csrf))return;
  proposal.value=null;generatedFor.value=null;clearConversation();message.value='';trace.value=[];savedNotice.value='';
  hydrateConversation(result?.conversation);
  await refreshConversationHistory();
 }catch{error.value='这条对话暂时无法恢复，请刷新历史后重试。';}finally{busyConversation.value=false;}
}
function selectQuickReply(value){
 if(followUpActive.value){answer.value=value;void generate({supplement:true});return;}
 message.value=value;void generate();
}
function openManual(){const date=view.value?.escalation?.prefill?.target_date;emit('manual-request',{target_date:typeof date==='string'?date:''});}

function applyAnswer(resultStatus,conversation,handedOver){
 if(handedOver)dispatch('ANSWER_ESCALATED',{conversation});
 else if(resultStatus==='needs_input')dispatch('ANSWER_NEEDS_INPUT',{conversation});
 else if(resultStatus==='ready')dispatch('ANSWER_READY',{conversation});
 else if(resultStatus==='unsupported')dispatch('ANSWER_UNSUPPORTED',{conversation});
 else{dispatch('FAIL',{code:'invalid_response'});error.value='助手返回了无法识别的结果，请重试。';}
}
async function generate({supplement=false}={}){
 if(busyConversation.value||!authorized()||!canStart.value||!isLegal(machine.value.name,'SEND')||!message.value.trim()||(supplement&&!answer.value.trim()))return;
 if(!props.credentialId){error.value='先在右上角选择预约凭据。';return;}
 const nextQuestions=supplement?[...questionHistory.value,[...questionList.value]]:[...questionHistory.value];
 const nextReplies=supplement?[...replyHistory.value,contextualReply.value]:[...replyHistory.value];
 const nextHeadings=supplement?[...roundHeadings.value,view.value?.heading||'']:[...roundHeadings.value];
 const nextAnswers=supplement?[...answers.value,answer.value.trim()]:[...answers.value];
 const nextAsked=supplement?[...askedFields.value,view.value?.asking??null]:[...askedFields.value];
 if(supplement&&nextAnswers.length>MAX_ANSWERS){error.value='这次补充的次数已用完。可以重新开始，或改用“选择预约”页手动选场。';return;}
 const generation=epoch,id=props.session.user.user_id,csrf=props.session.csrfToken,sequence=++requestId,userMessage=message.value.trim(),credentialId=props.credentialId,scopeLabel=props.scopeLabel;
 emit('mode-started');
 dispatch('SEND');error.value='';savedNotice.value='';proposal.value=null;generatedFor.value=null;
 pendingTurn.value=supplement?answer.value.trim():'';
 if(!supplement||trace.value.length===0)trace.value=[];
 traceEvent(supplement?'提交补充回答':'提交预约需求',supplement?'继续核对当前必填步骤。':'先确认队列类型，再按顺序核对日期、2小时和1小时队列。');
 try{
  const result=await props.proposalApi.generate({message:userMessage,credentialId,answers:nextAnswers,askedFields:nextAsked,scopeLabel,...(conversationId.value?{conversationId:conversationId.value}:{})});
  if(!valid(generation,id,csrf)||sequence!==requestId)return;
  if(typeof result.conversation_id==='string')conversationId.value=result.conversation_id;
  answers.value=nextAnswers;questionHistory.value=nextQuestions;replyHistory.value=nextReplies;askedFields.value=nextAsked;roundHeadings.value=nextHeadings;
  if(supplement)answer.value='';
  pendingTurn.value='';
  const conversation=result.conversation??null,handedOver=Boolean(conversation?.escalation);
  contextualReply.value=conversation?.contextual_reply||'';
  proposal.value=result.proposal;
  questions.value=handedOver?[]:result.status==='needs_input'?(result.questions||[]).slice(0,1):(result.questions||[]);
  applyAnswer(result.status,conversation,handedOver);
  generatedFor.value={message:userMessage,credentialId,scopeLabel};
  if(contextualReply.value)traceEvent('回答了当前问题','按已知规则回答，并继续保持当前预约核对顺序。');
  if(handedOver)traceEvent('建议改用手动选场','这一项多次没能确认，或补充次数已用完；已确认的日期可以带到“选择预约”页。');
  else if(result.status==='needs_input')traceEvent(`待确认：${conversation?.heading||'预约信息'}`,`这一步完成前不会进入后续队列字段。当前没有保存任何队列。`);
  else if(result.status==='ready')traceEvent('候选队列已整理好',`共 ${result.proposal.entry_count} 项，按执行顺序排好；等待你核对并确认保存。`);
  else traceEvent('请求不属于整理范围','助手不会代为查询、预约、付款或创建任务。');
  void refreshConversationHistory();
 }catch(err){
  if(!valid(generation,id,csrf)||sequence!==requestId)return;
  pendingTurn.value='';traceEvent('请求未完成','请查看提示后重试；没有保存任何队列。');
  dispatch('FAIL',{code:err?.code});
  error.value=err?.code==='credential_not_found'?'找不到这个预约凭据，请重新选择。':err?.code==='invalid_model_proposal'?'模型返回的内容不符合格式，请重试。':`整理失败：${providerErrorMessage(err?.code)}`;
  if(err?.code?.startsWith('provider_')&&err.code!=='provider_rate_limited')emit('provider-unavailable',err.code);
 }finally{if(valid(generation,id,csrf)&&sequence===requestId&&status.value==='generating')dispatch('INPUT_CHANGED');}
}
const savedKeys=candidates=>candidates.map(c=>[c.duration_minutes,c.preferred_start_times?.[0]??c.start_time,c.court_preferences?.[0]??c.court_preference,c.query_scope_label??c.scope_label??null]);
async function finishSaved(current,queue){
 savedNotice.value=`队列已保存 · ${current.target_label} · 共 ${current.entry_count} 项候选`;
 traceEvent('队列保存成功',`已写入“选择预约”队列（${current.target_date}）。`);
 proposal.value=null;generatedFor.value=null;dispatch('SAVE_OK');clearConversation();
 await closeCurrentConversation();
 emit('saved',{target_date:current.target_date,queue});emit('refresh-request');
}
async function confirmLanded(current,credentialId){
 try{
  const result=await props.planApi.queue(current.target_date,credentialId);
  const queue=result.queue;
  const landed=queue?.target_date===current.target_date&&queue?.credential_id===credentialId
   &&Number.isSafeInteger(queue.version)&&queue.version>=current.base_version&&queue.version<=current.base_version+1
   &&JSON.stringify(savedKeys(queue.candidates||[]))===JSON.stringify(savedKeys(current.entries));
  return landed?queue:null;
 }catch{return null;}
}
async function saveProposal(){
 if(!canSave.value)return;
 const generation=epoch,id=props.session.user.user_id,csrf=props.session.csrfToken,captured=generatedFor.value,current=proposal.value;
 dispatch('SAVE');error.value='';savedNotice.value='';traceEvent('你确认保存队列','已提交保存请求；不会在此步骤预约或付款。');
 try{
  const result=await props.planApi.saveQueue(current.target_date,current.base_version,current.entries,captured.credentialId);
  if(!valid(generation,id,csrf))return;
  await finishSaved(current,result.queue);
 }catch(err){
  if(!valid(generation,id,csrf))return;
  if(err?.code==='plan_version_conflict'){error.value='这一天的队列刚被改过。你的描述还在，点“重新整理”会基于最新队列重新生成。';traceEvent('队列版本冲突','队列已被更新；请重新整理后再保存。');dispatch('SAVE_CONFLICT');}
  else if(err?.status===400){error.value='队列未保存，请重新整理后再试。';traceEvent('队列保存失败','服务端拒绝了这份队列。');}
  else if(err?.kind==='network'||err?.kind==='timeout'||!err?.status||err.status>=500){
   const queue=await confirmLanded(current,captured.credentialId);
   if(!valid(generation,id,csrf))return;
   if(queue)await finishSaved(current,queue);
   else{error.value='保存结果暂时无法确认。请到“选择预约”页看这一天的队列，再决定要不要重新整理。';traceEvent('保存结果待核对','连接中断，尚不能确定服务端是否完成保存。');}
  }else{error.value='队列保存失败，请稍后重试。';traceEvent('队列保存失败','服务端未确认保存成功；当前建议仍保留。');}
 }finally{if(valid(generation,id,csrf)&&busySaving.value)dispatch('SAVE_REJECTED');}
}
onBeforeUnmount(()=>{alive=false;epoch++;requestId++;});
</script>

<template>
 <section class="proposal-assistant" aria-label="AI预约助手">
  <ProposalConversationHistory :message="message" :answers="answers" :question-history="questionHistory" :reply-history="replyHistory" :round-headings="roundHeadings" :questions="questionList" :heading="view?.heading||''" :asking="view?.asking||''" :contextual-reply="contextualReply" :pending-turn="pendingTurn" :status="status" :error="error" :saved-notice="savedNotice" :trace="trace" :slots="[]" :show-credential-status="Boolean(credentialApi)" :show-conversation-history="true" :conversations="conversations" :active-conversation-id="conversationId" :mode-choices="modeChoices" :interaction-disabled="status==='generating'||busySaving||busyConversation||!canStart" assistant-subtitle="选好类型后，我按顺序确认日期、时段和对应场地；也可以问我规则。" welcome-title="先选这次要排哪种队列" welcome-description="1小时和2小时的时间、场地分别确认，互不借用。" welcome-example="1 / A 只抢2小时 · 2 / B 只抢1小时 · 3 / C 两种都抢" welcome-footer="也可以直接描述需求；缺少的必填信息我会逐项询问。" @restart="restartConversation" @new-conversation="restartConversation" @select-conversation="selectConversation" @quick-reply="selectQuickReply">
   <template #header-actions><slot name="header-actions" /></template>
   <template #system-message><AgentCredentialGate v-if="credentialApi" :api="credentialApi" :session="session" :credential-id="credentialId" :refresh-key="credentialRefreshKey" @ready-change="credentialReady=$event" /></template>
   <template #queue-preview><ProposalQueuePreview :slots="view?.slots||[]" :proposal="proposal" /></template>
   <template #conversation-extra>
    <li v-for="note in notices" :key="note" class="chat-row is-assistant" data-testid="conversation-notice"><div class="chat-bubble">{{ note }}</div></li>
    <li v-if="escalated" class="chat-row is-assistant"><div class="chat-bubble bubble-artifact">
     <section class="verification-panel" aria-label="改用手动选场" data-testid="escalation-card">
      <h3>这一步改手动更稳妥</h3><p>{{ view?.escalation?.message }}</p>
      <p v-if="view?.escalation?.prefill?.target_date" class="muted">已确认日期：{{ dateText(view.escalation.prefill.target_date) }}</p>
      <div class="proposal-actions"><button class="primary-button" data-testid="open-manual" type="button" @click="openManual">去“选择预约”手动选场</button><button class="secondary-button" data-testid="escalation-restart" type="button" @click="restartConversation">重新开始对话</button></div>
     </section>
    </div></li>
    <li v-if="status==='needs_input'&&!escalated" class="chat-row is-assistant"><div class="chat-bubble"><button class="secondary-button" data-testid="cancel-proposal" type="button" @click="cancelProposal">取消本轮整理</button></div></li>
    <li v-if="proposal" class="chat-row is-assistant"><div class="chat-bubble bubble-artifact">
     <section class="proposal-result" aria-label="候选队列预览" data-testid="queue-preview">
      <div class="proposal-result-heading"><div><span class="eyebrow">队列预览</span><h3>{{ proposal.target_label }} · 共 {{ proposal.entry_count }} 项候选</h3></div><span v-if="proposal.provider" class="proposal-provider">{{ proposal.provider.name }} · {{ proposal.provider.model }}</span></div>
      <p class="muted" data-testid="queue-order-note">{{ proposal.execution_note }}</p>
      <ol class="queue-list" data-testid="queue-entries"><li v-for="(entry,index) in entries" :key="`${entry.duration_minutes}-${entry.start_time}-${entry.court_preference}`"><span class="queue-index">{{ index+1 }}</span>{{ entryText(entry) }}</li></ol>
      <p v-if="proposal.replaces_existing" class="proposal-feedback warn" role="status" data-testid="replace-warning">这一天已经有 {{ proposal.existing_count }} 项候选，保存后会被这份队列替换。</p>
      <p class="proposal-feedback" :class="scheduleClass" role="status" data-testid="queue-schedule">{{ proposal.schedule?.text }}</p>
      <div v-if="warnings.length" class="proposal-review" data-testid="review-warnings"><strong>模型复核提醒（仅供参考）</strong><ul><li v-for="warning in warnings" :key="warning">{{ warning }}</li></ul></div>
      <p v-if="proposal.review?.state==='skipped'" class="muted">{{ proposal.review.note }}</p>
      <p v-if="targetChanged" class="proposal-feedback error" role="status">描述已变化。请重新整理后再保存。</p>
      <p v-if="!scopeLabel||scopeChanged" class="proposal-feedback error" role="status">预约类别尚未读取或已变化。请先到“查询场地”读取当前 Token 的类别，再重新整理。</p>
      <p v-if="stale||scopeChanged" class="proposal-conflict-action"><button class="secondary-button" data-testid="regenerate" type="button" :disabled="status==='generating'||busySaving" @click="generate()">重新整理</button></p>
      <p class="proposal-safety" data-testid="proposal-quality-note">本步骤只保存候选队列，不会立即预约或付款。开票前会按真实场地表核对，用不上的候选会被去掉。</p>
      <div class="proposal-actions"><button class="primary-button" data-testid="confirm-save-proposal" type="button" :disabled="!canSave" @click="saveProposal">{{ busySaving?'正在保存…':'确认并保存队列' }}</button><button class="secondary-button" data-testid="cancel-proposal" type="button" :disabled="busySaving" @click="cancelProposal">取消建议</button></div>
     </section>
    </div></li>
   </template>
   <template #composer>
    <p v-if="editingOriginal && !resetNotice" class="composer-hint">正在修改原描述。改动后需要确认，才会清除已回答的问题。<button class="text-button" type="button" @click="editingOriginal=false">返回补充</button></p>
    <p v-if="resetNotice" class="proposal-feedback error" role="status">描述已变化。继续会清除已经回答的问题。
     <button class="secondary-button" type="button" @click="applyMessageReset">清除回答并使用新描述</button>
     <button class="text-button" type="button" @click="cancelMessageReset">保留原描述</button>
    </p>
    <ProposalComposer :message="resetNotice ? pendingMessage : message" :answer="answer" :status="status" :business-date="view?.business_date||''" :follow-up="followUpActive&&!editingOriginal" :busy="status==='generating'||busySaving||busyConversation" :blocked="!canStart" :send-blocked="resetNotice||editingOriginal" :suppressed="Boolean(credentialApi)&&!canStart" :locked="escalated" @update:message="onMessageInput" @update:answer="answer=$event" @edit-request="editingOriginal=true" @send="supplement=>generate({supplement})" />
   </template>
  </ProposalConversationHistory>
 </section>
</template>

<style scoped>
.proposal-assistant { min-width: 0; margin-bottom:24px; }
.proposal-result, .verification-panel { display: grid; gap:16px; padding:16px; border: 1px solid var(--line); border-radius:16px; background: var(--surface); }
.proposal-result h3, .verification-panel h3, .proposal-result p, .verification-panel p { margin:0; }
.verification-panel { border-color: var(--warning); background: var(--warning-soft); }
.proposal-result-heading { display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap:8px; }
.proposal-result-heading h3 { margin-top:8px; font-size: 17px; }
.proposal-provider { color: var(--muted); background: var(--page); padding:8px 8px; border-radius:8px; font-size: 12px; }
.proposal-actions { display: flex; align-items: center; flex-wrap: wrap; gap:8px; padding-top:8px; }
.proposal-actions button { min-height:var(--control-height); }
.queue-list { display: grid; gap:8px; margin:0; padding:0; max-height: 240px; overflow-y: auto; list-style: none; }
.queue-list li { display: flex; align-items: center; gap:8px; padding:8px 16px 8px 8px; border-radius:8px; background: var(--page); font-size: 15px; font-variant-numeric: tabular-nums; }
.queue-index { flex: none; width: 24px; height: 24px; display: grid; place-items: center; border-radius:50%; background: var(--brand-soft); color: var(--brand); font-size: 12px; font-weight: 600; }
.proposal-safety { padding:8px 16px; border-radius:8px; background: var(--page); color: var(--muted); font-size: 13px; }
.proposal-feedback { padding:8px 16px; margin:0; border-radius:8px; }
.proposal-feedback.error { background: var(--danger-soft); color: var(--danger); }
.proposal-feedback.warn, .proposal-feedback.is-warn { background: var(--warning-soft); color: var(--warning); }
.proposal-feedback.is-ok { background: var(--success-soft); color: var(--success); }
.proposal-review { display: grid; gap:8px; padding:8px 16px; border-radius:8px; background: var(--warning-soft); color: var(--ink); font-size: 14px; }
.proposal-review ul { margin:0; padding-left:16px; }
.proposal-conflict-action { margin:0 !important; }
.proposal-assistant :deep(button:focus-visible) { outline: 3px solid var(--brand); outline-offset: 2px; }
@media (max-width: 600px) {
  .proposal-actions { display: grid; grid-template-columns: 1fr; }
  .proposal-actions button { width: 100%; }
}
</style>
