import { computed, onBeforeUnmount, ref, shallowRef, watch } from 'vue';
import { copy, newIntent } from '../utils/planForm.js';

export function usePlans(api, session) {
  const plans=ref([]), context=shallowRef(null), defaultWindow=shallowRef(null), source=shallowRef(null);
  const listStatus=shallowRef('idle'), metadataError=shallowRef(''), saving=shallowRef(false), message=shallowRef('');
  const saveError=shallowRef(''), fields=shallowRef({}), conflict=shallowRef(false), latest=shallowRef(null), latestError=shallowRef('');
  const history=ref([]), historyPlanId=shallowRef(null), historyStatus=shallowRef('idle');
  const windowState=shallowRef(null), windowError=shallowRef(''), uncertain=shallowRef(false);
  const authorized=computed(()=>session?.status==='authenticated' && Boolean(session.user?.user_id));
  const canCreate=computed(()=>authorized.value && context.value && defaultWindow.value && !saving.value);
  let alive=true, epoch=0, listSequence=0, windowSequence=0, historySequence=0, latestSequence=0;
  const valid=(generation)=>alive && generation===epoch && authorized.value;
  function clearFeedback() { message.value='';saveError.value='';fields.value={};conflict.value=false;latest.value=null;latestError.value='';uncertain.value=false;latestSequence++; }
  function clearAll() {
    plans.value=[];context.value=null;defaultWindow.value=null;source.value=null;listStatus.value='idle';metadataError.value='';saving.value=false;
    history.value=[];historyPlanId.value=null;historyStatus.value='idle';windowState.value=null;windowError.value='';clearFeedback();
    listSequence++;windowSequence++;historySequence++;
  }
  async function refresh() {
    if (!authorized.value || saving.value) return;
    const generation=epoch, sequence=++listSequence;
    listStatus.value='loading';
    try { const result=await api.list();if(valid(generation)&&sequence===listSequence){plans.value=result.plans;listStatus.value='ready';} }
    catch {if(valid(generation)&&sequence===listSequence){plans.value=[];listStatus.value='error';}}
  }
  async function initialize() {
    const generation=epoch;
    await Promise.all([refresh(), (async()=>{
      try { const [options,window]=await Promise.all([api.options(),api.window()]);if(valid(generation)){context.value=options.context;defaultWindow.value=window;metadataError.value='';} }
      catch {if(valid(generation))metadataError.value='计划配置读取失败，请重新读取后再新建。';}
    })()]);
  }
  function setSource(plan) {
    windowSequence++;clearFeedback();
    source.value={planId:plan.plan_id,baseVersion:plan.version,intent:copy(plan.intent),context:copy(plan.context)};
    windowState.value=plan.booking_window;windowError.value='';
  }
  function startNew() {
    if(!canCreate.value)return;
    windowSequence++;clearFeedback();
    source.value={planId:null,baseVersion:null,intent:newIntent(defaultWindow.value.default_target_date),context:copy(context.value)};
    windowState.value=null;windowError.value='';
  }
  function edit(plan) {if(authorized.value&&!saving.value)setSource(plan);}
  function cancel() {if(!saving.value){source.value=null;windowState.value=null;windowSequence++;clearFeedback();}}
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
      const result=selected.planId ? await api.update(selected.planId,selected.baseVersion,intent) : await api.create(intent);
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
    try {const result=await api.get(selected.planId);if(valid(generation)&&sequence===latestSequence&&source.value===selected)latest.value=result.plan;}
    catch {if(valid(generation)&&sequence===latestSequence)latestError.value='最新版本读取失败，请重试；表单内容已保留。';}
  }
  function adoptLatest(){if(latest.value&&!saving.value)setSource(latest.value);}
  async function showHistory(planId) {
    if(!authorized.value)return;
    const generation=epoch,sequence=++historySequence;
    historyPlanId.value=planId;history.value=[];historyStatus.value='loading';
    try {const result=await api.revisions(planId);if(valid(generation)&&sequence===historySequence){history.value=result.revisions;historyStatus.value='ready';}}
    catch {if(valid(generation)&&sequence===historySequence)historyStatus.value='error';}
  }
  function closeHistory(){historyPlanId.value=null;history.value=[];historySequence++;}
  function acknowledgeUncertain(){if(authorized.value)uncertain.value=false;}
  watch(()=>[session?.status,session?.user?.user_id,session?.csrfToken],()=>{epoch++;clearAll();if(authorized.value)void initialize();},{immediate:true,flush:'sync'});
  onBeforeUnmount(()=>{alive=false;epoch++;clearAll();});
  return {plans,context,source,listStatus,metadataError,saving,message,saveError,fields,conflict,latest,latestError,history,historyPlanId,historyStatus,windowState,windowError,uncertain,authorized,canCreate,refresh,initialize,startNew,edit,cancel,updateWindow,save,viewLatest,adoptLatest,showHistory,closeHistory,acknowledgeUncertain};
}
