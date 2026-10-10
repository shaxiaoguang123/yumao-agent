import { computed, onBeforeUnmount, shallowRef, watch } from 'vue';

export function useAvailabilitySimulation(api, session, plans) {
  const options=shallowRef(null),optionsError=shallowRef(''),loadingOptions=shallowRef(false);
  const planId=shallowRef(''),scenario=shallowRef('complete'),result=shallowRef(null),error=shallowRef(''),busy=shallowRef(false);
  const selectedPlan=computed(()=>plans.value.find(plan=>plan.plan_id===planId.value)||null);
  const authorized=()=>session.status==='authenticated'&&Boolean(session.user?.user_id);
  const canMatch=computed(()=>authorized()&&options.value?.enabled===true&&Boolean(selectedPlan.value)&&!busy.value);
  let alive=true,epoch=0,sequence=0,optionsSequence=0;
  const valid=(generation,id,csrf)=>alive&&generation===epoch&&authorized()&&session.user?.user_id===id&&session.csrfToken===csrf;
  async function loadOptions(){
    if(!authorized())return;
    const generation=epoch,id=session.user.user_id,csrf=session.csrfToken,request=++optionsSequence;
    loadingOptions.value=true;optionsError.value='';
    try{const response=await api.options();if(valid(generation,id,csrf)&&request===optionsSequence)options.value=response;}
    catch{if(valid(generation,id,csrf)&&request===optionsSequence){options.value=null;optionsError.value='模拟场景读取失败，请重试。';}}
    finally{if(valid(generation,id,csrf)&&request===optionsSequence)loadingOptions.value=false;}
  }
  async function match(){
    if(!canMatch.value)return;
    const generation=epoch,id=session.user.user_id,csrf=session.csrfToken,request=++sequence;
    const plan=selectedPlan.value,selectedScenario=scenario.value;
    busy.value=true;error.value='';result.value=null;
    try{
      const response=await api.match(plan.plan_id,plan.version,selectedScenario);
      if(!valid(generation,id,csrf)||request!==sequence)return;
      if(response.simulation!==true||response.source?.simulation!==true||response.mode!=='simulation'
        ||response.plan_id!==plan.plan_id||response.base_version!==plan.version){error.value='返回数据未明确标记为当前计划的模拟结果，已停止展示。';return;}
      result.value=response;
    }catch(failure){
      if(!valid(generation,id,csrf)||request!==sequence)return;
      error.value=failure.code==='plan_version_conflict'?'计划版本已变化，请刷新计划列表后重新选择并匹配。'
        :failure.code==='simulation_not_enabled'?'本环境未启用模拟匹配。'
        :failure.code==='availability_timezone_day_unsupported'?'该日期存在时区偏移变化，本版时段契约不能安全匹配。请选择其他日期。'
        :'模拟匹配失败，请稍后重试；预约计划未被修改。';
    }finally{if(valid(generation,id,csrf)&&request===sequence)busy.value=false;}
  }
  watch(()=>[session.status,session.user?.user_id,session.csrfToken],()=>{
    epoch++;sequence++;optionsSequence++;options.value=null;optionsError.value='';loadingOptions.value=false;
    planId.value='';scenario.value='complete';result.value=null;error.value='';busy.value=false;
    if(authorized())void loadOptions();
  },{immediate:true,flush:'sync'});
  watch(()=>[planId.value,selectedPlan.value?.version,scenario.value],()=>{sequence++;result.value=null;error.value='';busy.value=false;},{flush:'sync'});
  onBeforeUnmount(()=>{alive=false;epoch++;sequence++;optionsSequence++;result.value=null;});
  return {options,optionsError,loadingOptions,planId,scenario,result,error,busy,canMatch,loadOptions,match};
}
