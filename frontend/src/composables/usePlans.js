import { computed, onBeforeUnmount, ref, shallowRef, watch } from 'vue';
import { copy, newIntent } from '../utils/planForm.js';

export function usePlans(api, session, targetCredentialId=()=>null) {
  const plans=ref([]), context=shallowRef(null), defaultWindow=shallowRef(null), catalog=shallowRef(null), source=shallowRef(null);
  const listStatus=shallowRef('idle'), metadataError=shallowRef(''), saving=shallowRef(false), message=shallowRef('');
  const saveError=shallowRef(''), fields=shallowRef({}), conflict=shallowRef(false), latest=shallowRef(null), latestError=shallowRef('');
  const history=ref([]), historyPlanId=shallowRef(null), historyStatus=shallowRef('idle');
  const windowState=shallowRef(null), windowError=shallowRef(''), uncertain=shallowRef(false);
  const authorized=computed(()=>session?.status==='authenticated' && Boolean(session.user?.user_id));
  const credentialId=computed(()=>typeof targetCredentialId==='function'?targetCredentialId():targetCredentialId?.value||targetCredentialId||null);
  const canCreate=computed(()=>authorized.value && context.value && defaultWindow.value && !saving.value);
  let alive=true, epoch=0, sourceSelectionSequence=0, listSequence=0, windowSequence=0, historySequence=0, latestSequence=0;
  let suspendedDraft=null,recoveryUserId=null,lastInvalidationEpoch=session?.invalidationEpoch??0;
  const valid=(generation)=>alive && generation===epoch && authorized.value;
  function clearFeedback() { message.value='';saveError.value='';fields.value={};conflict.value=false;latest.value=null;latestError.value='';uncertain.value=false;latestSequence++; }
  function clearAll() {
    sourceSelectionSequence++;
    plans.value=[];context.value=null;defaultWindow.value=null;catalog.value=null;source.value=null;listStatus.value='idle';metadataError.value='';saving.value=false;
    history.value=[];historyPlanId.value=null;historyStatus.value='idle';windowState.value=null;windowError.value='';clearFeedback();
    listSequence++;windowSequence++;historySequence++;
  }
  async function refresh() {
    if (!authorized.value || saving.value) return;
    const generation=epoch, sequence=++listSequence;
    listStatus.value='loading';
    try { const result=credentialId.value?await api.list(credentialId.value):await api.list();if(valid(generation)&&sequence===listSequence){plans.value=result.plans;listStatus.value='ready';} }
    catch {if(valid(generation)&&sequence===listSequence){plans.value=[];listStatus.value='error';}}
  }
  async function initialize() {
    const generation=epoch;
    await Promise.all([refresh(), (async()=>{
      try { const [options,window]=await Promise.all([api.options(),api.window()]);if(valid(generation)){context.value=options.context;defaultWindow.value=window;catalog.value=options;metadataError.value='';} }
      catch {if(valid(generation))metadataError.value='计划配置读取失败，请重新读取后再新建。';}
    })()]);
  }
  function setSource(plan) {
    sourceSelectionSequence++;
    windowSequence++;clearFeedback();
    source.value={planId:plan.plan_id,baseVersion:plan.version,credentialId:plan.credential_id||null,intent:copy(plan.intent),context:copy(plan.context)};
    suspendedDraft={userId:session.user.user_id,source:copy(source.value)};
    windowState.value=plan.booking_window;windowError.value='';
  }
  function startNew(targetDate=defaultWindow.value?.default_target_date) {
    if(!canCreate.value)return;
    sourceSelectionSequence++;
    windowSequence++;clearFeedback();
    source.value={planId:null,baseVersion:null,intent:newIntent(targetDate),context:copy(context.value)};
    suspendedDraft={userId:session.user.user_id,source:copy(source.value)};
    windowState.value=null;windowError.value='';
  }
  function edit(plan) {if(authorized.value&&!saving.value)setSource(plan);}
  function cancel() {if(!saving.value){sourceSelectionSequence++;source.value=null;windowState.value=null;windowSequence++;suspendedDraft=null;recoveryUserId=null;clearFeedback();}}
  function rememberDraft(draftState){
    if(!authorized.value||!source.value||typeOfDraft(draftState)!=='object')return;
    const updated=copy(source.value);updated.draftState=copy(draftState);source.value.draftState=updated.draftState;
    suspendedDraft={userId:session.user.user_id,source:updated};
  }
  async function updateWindow(targetDate) {
    if(!authorized.value || !source.value)return;
    const generation=epoch, sequence=++windowSequence, selected=source.value;
    windowState.value=null;windowError.value='';
    if(!targetDate)return;
    try {const result=await api.window(targetDate,selected.planId);if(valid(generation)&&sequence===windowSequence&&source.value===selected)windowState.value=result;}
    catch {if(valid(generation)&&sequence===windowSequence)windowError.value='日期窗口读取失败，保存不会进行任何上游查询。';}
  }
  async function save(intent) {
    if(!authorized.value || saving.value || !source.value || conflict.value || uncertain.value)return;
    const generation=epoch, selected=source.value;
    saving.value=true;saveError.value='';fields.value={};message.value='';
    try {
      const result=selected.planId ? (selected.credentialId?await api.update(selected.planId,selected.baseVersion,intent,selected.credentialId):await api.update(selected.planId,selected.baseVersion,intent)) : (credentialId.value?await api.create(intent,credentialId.value):await api.create(intent));
      if(!valid(generation))return;
      plans.value=[result.plan,...plans.value.filter(item=>item.plan_id!==result.plan.plan_id)];listStatus.value='ready';
      setSource(result.plan);message.value=`已保存预约意向 · 版本 ${result.plan.version}`;
      if(historyPlanId.value===result.plan.plan_id)await showHistory(result.plan.plan_id);
    } catch(error) {
      if(!valid(generation))return;
      if(error.status===409){conflict.value=true;saveError.value='版本冲突：计划已被其他窗口更新。你的未保存内容仍保留。';}
      else if(error.status===400){fields.value=error.fields||{};saveError.value='请检查表单字段后再保存。';}
      else if(error.sessionInvalid){saveError.value='登录状态已失效，请重新登录。';}
      else {uncertain.value=true;saveError.value='保存结果尚未确认。请读取计划列表或最新版本核对，再决定是否重新保存。';}
    } finally {if(valid(generation))saving.value=false;}
  }
  async function viewLatest() {
    if(!authorized.value || !source.value?.planId)return;
    const generation=epoch, sequence=++latestSequence, selected=source.value;
    latest.value=null;latestError.value='';
    try {const result=selected.credentialId?await api.get(selected.planId,selected.credentialId):await api.get(selected.planId);if(valid(generation)&&sequence===latestSequence&&source.value===selected)latest.value=result.plan;}
    catch {if(valid(generation)&&sequence===latestSequence)latestError.value='最新版本读取失败，请重试；表单内容已保留。';}
  }
  function adoptLatest(){if(latest.value&&!saving.value)setSource(latest.value);}
  async function showHistory(planId) {
    if(!authorized.value)return;
    const generation=epoch,sequence=++historySequence;
    historyPlanId.value=planId;history.value=[];historyStatus.value='loading';
    const plan=plans.value.find(item=>item.plan_id===planId);
    try {const result=plan?.credential_id?await api.revisions(planId,plan.credential_id):await api.revisions(planId);if(valid(generation)&&sequence===historySequence){history.value=result.revisions;historyStatus.value='ready';}}
    catch {if(valid(generation)&&sequence===historySequence)historyStatus.value='error';}
  }
  function closeHistory(){historyPlanId.value=null;history.value=[];historySequence++;}
  async function remove(plan){
    if(!authorized.value||saving.value)return;
    const generation=epoch;saving.value=true;saveError.value='';message.value='';
    try{if(plan.credential_id)await api.remove(plan.plan_id,plan.version,plan.credential_id);else await api.remove(plan.plan_id,plan.version);if(!valid(generation))return;
      plans.value=plans.value.filter(item=>item.plan_id!==plan.plan_id);
      if(source.value?.planId===plan.plan_id){source.value=null;suspendedDraft=null;}
      message.value='计划已删除，历史修订已保留。';
    }catch(error){if(valid(generation))saveError.value=error?.status===409?'版本冲突：计划已更新，请重新读取后删除。':'删除结果未确认，请重新读取计划核对。';}
    finally{if(valid(generation))saving.value=false;}
  }
  function acknowledgeUncertain(){if(authorized.value)uncertain.value=false;}
  watch(()=>[session?.status,session?.user?.user_id,session?.csrfToken,session?.invalidationEpoch,credentialId.value],()=>{
    const userId=session?.user?.user_id||null;
    const invalidationEpoch=session?.invalidationEpoch??0;
    const invalidated=invalidationEpoch!==lastInvalidationEpoch;
    lastInvalidationEpoch=invalidationEpoch;
    if(invalidated&&authorized.value&&session?.invalidatedUserId===userId){
      if(source.value){const preserved=copy(source.value);suspendedDraft={userId,source:preserved};}
      recoveryUserId=userId;
      return;
    }
    if(userId&&suspendedDraft&&userId!==suspendedDraft.userId)suspendedDraft=null;
    if(userId&&recoveryUserId&&userId!==recoveryUserId)recoveryUserId=null;
    if(!userId&&recoveryUserId===null)suspendedDraft=null;
    if(authorized.value&&recoveryUserId===userId&&!suspendedDraft)recoveryUserId=null;
    const restore=recoveryUserId===userId&&suspendedDraft?.userId===userId?copy(suspendedDraft):null;
    if(userId&&!restore&&recoveryUserId===null) suspendedDraft=null;
    const generation=++epoch;clearAll();
    const restoreSelectionSequence=sourceSelectionSequence;
    if(authorized.value){
      void initialize().then(()=>{
        if(!valid(generation))return;
        if(restore){
          if(sourceSelectionSequence!==restoreSelectionSequence||source.value!==null){
            recoveryUserId=null;
            return;
          }
          source.value=copy(restore.source);windowState.value=null;windowError.value='';
          message.value='登录已恢复，未保存表单已恢复；请重新生成网格并保存时确认版本。';
          recoveryUserId=null;suspendedDraft=null;
          void updateWindow(source.value.intent.target_date);
        }
      });
    }
  },{immediate:true,flush:'sync'});
  onBeforeUnmount(()=>{alive=false;epoch++;clearAll();});
  return {plans,context,defaultWindow,catalog,source,listStatus,metadataError,saving,message,saveError,fields,conflict,latest,latestError,history,historyPlanId,historyStatus,windowState,windowError,uncertain,authorized,canCreate,refresh,initialize,startNew,edit,cancel,updateWindow,save,remove,viewLatest,adoptLatest,showHistory,closeHistory,acknowledgeUncertain,rememberDraft};
}

function typeOfDraft(value){return value&&typeof value==='object'&&!Array.isArray(value)?'object':typeof value;}
