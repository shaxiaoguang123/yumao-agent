import { computed, ref, shallowRef, watch } from 'vue';

const minutes = value => typeof value==='string' && /^([01]\d|2[0-3]):[0-5]\d$/.test(value)
  ? Number(value.slice(0,2))*60+Number(value.slice(3)) : null;

// Client display observations can express an intent; this is not an inventory
// matcher or execution check. Row coordinates stay local and are never emitted.
export function useObservedIntentSelection(props, emit) {
  const selectedRows=ref(new Set()), courtOrder=ref([]), selectionError=shallowRef('');
  function clear(){selectedRows.value=new Set();courtOrder.value=[];selectionError.value='';}
  watch(()=>[props.grid,props.expired,props.contextKey],clear,{flush:'sync'});
  function canSelect(row,court){
    const slot=props.grid.rows[row],cell=slot?.cells[court];
    return !props.expired && !props.selectionDisabled && Date.now()<props.grid.source.ui_stale_after_utc_ms
      && props.grid.can_select_intent===true && props.grid.client_selection_window==='open'
      && slot?.time_status_code==='0' && cell?.state==='observed_clear_unmarked'
      && cell.intent_selectable===true && minutes(slot.intent_start_time)!==null
      && minutes(slot.intent_end_time)>minutes(slot.intent_start_time);
  }
  const selection=computed(()=>{
    const indexes=[...selectedRows.value].sort((a,b)=>a-b), primary=courtOrder.value[0];
    if(!indexes.length || primary===undefined)return {valid:false,message:''};
    if(indexes.some(row=>!canSelect(row,primary)))return {valid:false,message:'所选状态已失效，请刷新场地。'};
    const rows=indexes.map(index=>props.grid.rows[index]);
    if(rows.some((row,index)=>index>0 && rows[index-1].intent_end_time!==row.intent_start_time))
      return {valid:false,message:'请选择连续时间，不能跨越空档。'};
    const duration=minutes(rows.at(-1).intent_end_time)-minutes(rows[0].intent_start_time);
    if(duration<30 || duration>240 || duration%30!==0)return {valid:false,message:'意向时长须为30～240分钟，且为30分钟增量。'};
    const min=props.grid.selection_limits?.min_slots_observed??1;
    const max=props.grid.selection_limits?.max_slots_observed??6;
    if(indexes.length<min || indexes.length>max)return {valid:false,message:`请选择 ${min}～${max} 个连续时段。`};
    if(courtOrder.value.some(court=>indexes.some(row=>!canSelect(row,court))))
      return {valid:false,message:'备选场地没有覆盖完整的已选时段。'};
    return {valid:true,start:rows[0].intent_start_time,end:rows.at(-1).intent_end_time,duration};
  });
  function chosen(row,court){return selectedRows.value.has(row) && courtOrder.value.includes(court);}
  function toggle(row,court){
    if(!canSelect(row,court))return;
    selectionError.value='';
    if(!courtOrder.value.length)courtOrder.value=[court];
    if(court!==courtOrder.value[0]){
      if(courtOrder.value.includes(court)){courtOrder.value=courtOrder.value.filter(value=>value!==court);return;}
      if(!selection.value.valid || !selectedRows.value.has(row)
          || [...selectedRows.value].some(index=>!canSelect(index,court))){
        selectionError.value='先完成首选时间块，再点击同一时间块的可选场地添加备选。';return;
      }
      if(courtOrder.value.length>=16){selectionError.value='最多保存16个有序场地偏好。';return;}
      courtOrder.value=[...courtOrder.value,court];return;
    }
    const next=new Set(selectedRows.value);
    if(next.has(row))next.delete(row);else next.add(row);
    selectedRows.value=next;
    courtOrder.value=next.size?[court]:[];
  }
  function move(index,delta){
    const next=index+delta;if(next<0||next>=courtOrder.value.length)return;
    const order=[...courtOrder.value];[order[index],order[next]]=[order[next],order[index]];courtOrder.value=order;
  }
  function remove(index){
    courtOrder.value=courtOrder.value.filter((_value,position)=>position!==index);
    if(!courtOrder.value.length)clear();
  }
  function apply(){
    if(!selection.value.valid||props.expired||Date.now()>=props.grid.source.ui_stale_after_utc_ms)return;
    emit('apply',{
      target_date:props.grid.target_date,start_time:selection.value.start,end_time:selection.value.end,
      duration_minutes:selection.value.duration,
      court_preferences:courtOrder.value.map(index=>props.grid.courts[index].display_name),
      observation_expires_at_utc_ms:props.grid.source.ui_stale_after_utc_ms,
      observation_timezone_name:props.grid.timezone_name,
    });
  }
  return {selectedRows,courtOrder,selection,selectionError,canSelect,chosen,toggle,clear,move,remove,apply};
}
