<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue';

const props=defineProps({
  api:{type:Object,required:true},
  targetDate:{type:String,required:true},
  durationMinutes:{type:Number,required:true},
  venuePreference:{type:String,default:''},
  courtPreferences:{type:Array,default:()=>[]},
  timezoneName:{type:String,default:''},
  selectionContextKey:{type:String,default:''},
});
const emit=defineEmits(['update:targetDate','apply']);
const enabled=ref(false),optionsLoading=ref(true),optionsError=ref('');
const gridScenarios=ref([]),scenario=ref('partially_occupied');
const grid=ref(null),gridLoading=ref(false),gridError=ref(''),selectedRows=ref(new Set());
const primaryCourt=ref(null),backupCourts=ref([]),selectionMessage=ref(''),staleMessage=ref('');
const signature=computed(()=>JSON.stringify({
  target_date:props.targetDate,duration_minutes:props.durationMinutes,
  venue_preference:props.venuePreference,court_preferences:props.courtPreferences,
  timezone_name:props.timezoneName,selection_context:props.selectionContextKey,scenario:scenario.value,
}));
let alive=true,optionsEpoch=0,gridEpoch=0,loadedSignature='';

const stateLabels={
  selectable:'可选择（合成）',reserved:'已预订（合成）',
  activity_occupied:'活动占用（合成）',unbookable:'不可预订（合成）',unknown:'未知（不可选择）',
  historical_selectable:'历史观察：客户端曾显示可选',historical_reserved:'历史观察：客户端显示已预订',
  historical_activity_occupied:'历史观察：客户端显示活动占用',historical_unbookable:'历史观察：客户端显示不可预订',
  historical_unknown:'历史观察：状态未知',
};
const knownStates=new Set(Object.keys(stateLabels));
const canLoad=computed(()=>Boolean(props.targetDate&&props.venuePreference.trim()&&props.courtPreferences.length&&scenario.value));
const readOnlyGrid=computed(()=>grid.value?.simulation!==true||grid.value?.source?.data_state!=='synthetic');

function parseMinute(value,end=false){
  if(end&&value==='24:00')return 1440;
  if(typeof value!=='string'||!/^([01]\d|2[0-3]):[0-5]\d$/.test(value))return null;
  return Number(value.slice(0,2))*60+Number(value.slice(3));
}
function syntheticReplyError(result,request){
  if(result?.grid_version!=='venue-time-grid-v2'||result?.simulation!==true
      ||result?.scenario!==request.scenario||result?.source?.source!==`synthetic-v1:${request.scenario}`
      ||result?.source?.simulation!==true||result?.source?.data_state!=='synthetic'
      ||result?.source?.trust_state!=='synthetic'||result?.venue?.verification!=='unverified_manual'
      ||['can_query_upstream','can_book','can_pay','can_create_job'].some(key=>result?.[key]!==false))
    return '数据来源不是明确标记的合成网格，已停止展示。';
  if(result.target_date!==request.target_date||result.duration_minutes!==request.duration_minutes
      ||result.venue?.display_name!==request.venue_preference||result.timezone_name!==props.timezoneName
      ||(result.atom_minutes!==null&&(!Number.isInteger(result.atom_minutes)||result.atom_minutes<1)))
    return '网格数据与当前表单不一致，已停止展示；请重新读取。';
  if(!Array.isArray(result.courts)||JSON.stringify(result.courts.map(court=>court.display_name))!==JSON.stringify(request.court_preferences)
      ||result.courts.some(court=>court.verification!=='unverified_manual'))
    return '网格场地标签与当前人工偏好不一致，已停止展示。';
  if(!Array.isArray(result.rows)||!result.rows.length)return '网格状态数据不完整，已停止展示。';
  for(const row of result.rows){
    const start=parseMinute(row.start_time),end=parseMinute(row.end_time,true);
    if(start===null||end===null||start>=end||!Array.isArray(row.cells)||row.cells.length!==result.courts.length
        ||!row.cells.every(cell=>knownStates.has(cell.state)&&cell.state.startsWith('historical_')?cell.selectable===false
          :knownStates.has(cell.state)&&cell.selectable===(cell.state==='selectable')))
      return '网格状态数据不完整或含未知格式，已停止展示。';
  }
  return '';
}

async function loadOptions(){
  const epoch=++optionsEpoch;optionsLoading.value=true;optionsError.value='';
  try{
    const result=await props.api.options();
    if(!alive||epoch!==optionsEpoch)return;
    enabled.value=result.grid_preview_enabled===true;
    gridScenarios.value=Array.isArray(result.grid_scenarios)?result.grid_scenarios.filter(item=>typeof item?.id==='string'):[];
    if(!gridScenarios.value.some(item=>item.id===scenario.value))scenario.value=gridScenarios.value[0]?.id||'';
  }catch{
    if(alive&&epoch===optionsEpoch){enabled.value=false;optionsError.value='模拟网格状态读取失败。';}
  }finally{if(alive&&epoch===optionsEpoch)optionsLoading.value=false;}
}

function invalidateGrid(message=''){
  gridEpoch++;grid.value=null;selectedRows.value=new Set();primaryCourt.value=null;backupCourts.value=[];
  gridError.value='';selectionMessage.value='';loadedSignature='';staleMessage.value=message;
  gridLoading.value=false;
}
watch(signature,(next,previous)=>{
  if(next!==previous&&(loadedSignature||grid.value||selectedRows.value.size||gridLoading.value))
    invalidateGrid('预约意向字段或计划/会话上下文已变化，旧网格选择已清除；如需继续选格，请重新生成。');
},{flush:'sync'});

async function loadGrid(){
  if(!enabled.value||optionsLoading.value||gridLoading.value)return;
  if(!canLoad.value){gridError.value='请先填写目标日期、人工场馆描述、场地偏好和合成场景。';return;}
  const epoch=++gridEpoch,requestSignature=signature.value;
  gridLoading.value=true;gridError.value='';grid.value=null;selectedRows.value=new Set();primaryCourt.value=null;backupCourts.value=[];
  selectionMessage.value='';staleMessage.value='';loadedSignature='';
  try{
    const request={
      target_date:props.targetDate,duration_minutes:props.durationMinutes,
      venue_preference:props.venuePreference,court_preferences:[...props.courtPreferences],scenario:scenario.value,
    };
    const result=await props.api.gridPreview(request);
    if(!alive||epoch!==gridEpoch||requestSignature!==signature.value)return;
    const invalidReply=syntheticReplyError(result,request);
    if(invalidReply){gridError.value=invalidReply;return;}
    grid.value=result;loadedSignature=requestSignature;
  }catch{
    if(alive&&epoch===gridEpoch)gridError.value='合成网格读取失败；人工计划仍可继续编辑和保存。';
  }finally{if(alive&&epoch===gridEpoch)gridLoading.value=false;}
}

function keyFor(rowIndex,courtIndex){return `${rowIndex}:${courtIndex}`;}
function isSelected(rowIndex,courtIndex){return courtIndex===primaryCourt.value&&selectedRows.value.has(rowIndex);}
function cellAriaLabel(row,court,cell,chosen){
  return `${court.display_name} ${row.start_time}到${row.end_time}：${chosen?'已选择':stateLabels[cell.state]}${cell.category_label?`，${cell.category_label}`:''}`;
}
function toggleCell(rowIndex,courtIndex,cell){
  if(!cell?.selectable||readOnlyGrid.value||!grid.value)return;
  if(primaryCourt.value!==null&&primaryCourt.value!==courtIndex){
    selectionMessage.value='其他场地请使用下方“添加为备选场地”，并确认它覆盖相同的完整时段。';return;
  }
  if(primaryCourt.value===null)primaryCourt.value=courtIndex;
  const next=new Set(selectedRows.value);
  if(next.has(rowIndex))next.delete(rowIndex);else next.add(rowIndex);
  if(next.size!==selectedRows.value.size||backupCourts.value.length){backupCourts.value=[];}
  selectedRows.value=next;
  if(!next.size)primaryCourt.value=null;
  selectionMessage.value='';
}
function clearSelection(){selectedRows.value=new Set();primaryCourt.value=null;backupCourts.value=[];selectionMessage.value='';}

const selection=computed(()=>{
  if(!grid.value||!selectedRows.value.size||primaryCourt.value===null)return {hasSelection:false,valid:false,message:''};
  const indexes=[...selectedRows.value].sort((a,b)=>a-b);
  if(indexes.some(index=>!Number.isInteger(index)||!grid.value.rows[index]?.cells?.[primaryCourt.value]?.selectable))
    return {hasSelection:true,valid:false,message:'所选格子已失效，请重新选择。'};
  const rows=indexes.map(index=>grid.value.rows[index]);
  const intervals=rows.map(row=>({start:parseMinute(row.start_time),end:parseMinute(row.end_time,true)}));
  if(intervals.some(item=>item.start===null||item.end===null||item.start>=item.end))
    return {hasSelection:true,valid:false,message:'网格时间边界无法确认，请重新生成。'};
  if(intervals.some((item,index)=>index>0&&intervals[index-1].end!==item.start))
    return {hasSelection:true,valid:false,message:'实际时间不连续或跨越午夜，不能组成一个意向时段。'};
  const duration=intervals.reduce((total,item)=>total+item.end-item.start,0);
  if(duration!==grid.value.duration_minutes)
    return {hasSelection:true,valid:false,message:`所选连续时段为 ${duration} 分钟，需要完整覆盖 ${grid.value.duration_minutes} 分钟。`};
  const first=rows[0],last=rows.at(-1);
  return {hasSelection:true,valid:true,startTime:first.start_time,endTime:last.end_time,
    durationMinutes:duration,rowIndexes:indexes,
    courtNames:[primaryCourt.value,...backupCourts.value].map(index=>grid.value.courts[index].display_name),
    message:`${first.start_time}～${last.end_time} · ${duration} 分钟`};
});

function canAddBackup(courtIndex){
  if(!selection.value.valid||courtIndex===primaryCourt.value||backupCourts.value.includes(courtIndex)||readOnlyGrid.value)return false;
  return selection.value.rowIndexes.every(rowIndex=>grid.value.rows[rowIndex]?.cells?.[courtIndex]?.selectable===true);
}
function addBackup(courtIndex){if(canAddBackup(courtIndex))backupCourts.value=[...backupCourts.value,courtIndex];}
function removeBackup(index){backupCourts.value=backupCourts.value.filter((_court,position)=>position!==index);}
function moveBackup(index,delta){
  const target=index+delta;if(target<0||target>=backupCourts.value.length)return;
  const next=[...backupCourts.value];[next[index],next[target]]=[next[target],next[index]];backupCourts.value=next;
}
function promoteBackup(index){
  const nextPrimary=backupCourts.value[index];
  if(nextPrimary===undefined)return;
  backupCourts.value=[primaryCourt.value,...backupCourts.value.filter((_court,position)=>position!==index)];
  primaryCourt.value=nextPrimary;
}
function applySelection(){
  if(!selection.value.valid||!grid.value||loadedSignature!==signature.value)return;
  emit('apply',{target_date:grid.value.target_date,start_time:selection.value.startTime,
    end_time:selection.value.endTime,duration_minutes:selection.value.durationMinutes,
    court_preferences:[...selection.value.courtNames],scenario:grid.value.scenario});
}

onMounted(()=>void loadOptions());
onBeforeUnmount(()=>{alive=false;optionsEpoch++;gridEpoch++;});
</script>

<template>
  <section class="panel venue-time-grid" data-testid="venue-time-grid" aria-labelledby="venue-grid-title">
    <div class="grid-heading">
      <div><p class="eyebrow">人工意向网格</p><h3 id="venue-grid-title">选择首选场地与备选场地</h3></div>
      <span class="grid-source-badge">合成数据</span>
    </div>
    <p class="grid-notice">{{ grid?.notice||'网格中的状态来自同一份合成时段快照，并非真实场馆库存。选择只会整理意向，不会查询、预约或支付。' }}</p>
    <p class="muted grid-manual-labels">先选择一个完整连续时间段，再按顺序添加覆盖相同时间的备选场地。只会按顺序尝试一个场地，不代表同时预约多块场地。</p>
    <p v-if="optionsLoading" class="muted" role="status">正在读取网格能力…</p>
    <p v-else-if="optionsError" class="form-error" role="alert">{{ optionsError }} <button class="secondary-button" type="button" @click="loadOptions">重试</button></p>
    <p v-else-if="!enabled" class="muted" role="status">当前环境未启用模拟网格；手动时间和场地偏好仍可使用。</p>
    <template v-else>
      <div class="grid-load-controls">
        <label class="field">网格预览日期（同步计划）<input data-testid="grid-date" type="date" :value="targetDate" @input="emit('update:targetDate',$event.target.value)" /></label>
        <label v-if="gridScenarios.length" class="field">合成场景<select v-model="scenario" data-testid="grid-scenario"><option v-for="item in gridScenarios" :key="item.id" :value="item.id">{{ item.name }}</option></select></label>
        <button class="secondary-button" data-testid="grid-load" type="button" :disabled="gridLoading||!canLoad" @click="loadGrid">{{ gridLoading?'正在生成…':'生成模拟网格' }}</button>
      </div>
      <p v-if="!canLoad" class="muted" role="status">填写目标日期、人工场馆描述和至少一个场地偏好后，才能查看对应的合成示例。</p>
      <p v-if="gridError" class="form-error" role="alert">{{ gridError }}</p>
      <p v-if="staleMessage" class="form-error" role="status">{{ staleMessage }}</p>
      <p v-if="selectionMessage" class="form-error" role="status">{{ selectionMessage }}</p>
      <template v-if="grid">
        <p class="muted grid-manual-labels">场馆和列标题取自当前手工偏好。此合成场景每格 {{ grid.atom_minutes||'非固定' }} 分钟；最终时长按时间边界合计，不以行号推断。</p>
        <div class="grid-legend" aria-label="网格状态图例">
          <span v-for="state in ['selectable','reserved','activity_occupied','unbookable','unknown']" :key="state" class="grid-legend-item" :class="`state-${state}`">{{ stateLabels[state] }}</span>
        </div>
        <div class="grid-scroll" role="region" aria-label="合成场地时间网格" tabindex="0">
          <table class="venue-grid-table">
            <thead><tr><th scope="col">时间</th><th v-for="court in grid.courts" :key="court.display_name" scope="col">{{ court.display_name }}<small>人工偏好</small></th></tr></thead>
            <tbody>
              <tr v-for="(row,rowIndex) in grid.rows" :key="`${row.start_time}-${row.end_time}`">
                <th scope="row">{{ row.start_time }}～{{ row.end_time }}</th>
                <td v-for="(cell,courtIndex) in row.cells" :key="grid.courts[courtIndex].display_name">
                  <button :data-testid="`grid-cell-${rowIndex}-${courtIndex}`" class="grid-cell" :class="[`state-${cell.state}`,{'is-selected':isSelected(rowIndex,courtIndex)}]" type="button" :disabled="!cell.selectable||gridLoading||readOnlyGrid" :aria-pressed="isSelected(rowIndex,courtIndex)" :aria-label="cellAriaLabel(row,grid.courts[courtIndex],cell,isSelected(rowIndex,courtIndex))" @click="toggleCell(rowIndex,courtIndex,cell)">
                    {{ isSelected(rowIndex,courtIndex)?'已选为首选时段':stateLabels[cell.state] }}<small v-if="cell.category_label">{{ cell.category_label }}</small>
                  </button>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
        <div class="grid-selection-summary">
          <p v-if="selection.valid" role="status">已选完整时段：{{ selection.message }} · 首选场地：{{ grid.courts[primaryCourt].display_name }}</p>
          <p v-else-if="selection.hasSelection" class="form-error" role="status">{{ selection.message }}</p>
          <p v-else class="muted" role="status">先在一个场地列选择完整的连续时间。其他列需通过备选操作加入。</p>
          <p v-if="selection.valid" class="grid-nonconcurrent">只按顺序尝试一个场地，不代表同时预约多块场地。</p>
          <div v-if="selection.valid" class="grid-backup-editor" data-testid="grid-court-order">
            <div v-for="court in grid.courts" :key="court.display_name" class="grid-backup-add-row">
              <span>{{ court.display_name }}</span>
              <strong v-if="court.display_name===grid.courts[primaryCourt].display_name">当前首选</strong>
              <strong v-else-if="backupCourts.includes(grid.courts.indexOf(court))">已列为备选</strong>
              <button v-else class="secondary-button" :data-testid="`grid-add-backup-${grid.courts.indexOf(court)}`" type="button" :disabled="!canAddBackup(grid.courts.indexOf(court))" @click="addBackup(grid.courts.indexOf(court))">添加为备选场地</button>
            </div>
            <ol v-if="backupCourts.length" class="grid-backup-list">
              <li v-for="(courtIndex,index) in backupCourts" :key="grid.courts[courtIndex].display_name">
                <span>备选 {{ index+1 }}：{{ grid.courts[courtIndex].display_name }}</span>
                <div class="grid-backup-actions">
                  <button class="secondary-button" :data-testid="`grid-promote-backup-${index}`" type="button" @click="promoteBackup(index)">设为首选</button>
                  <button class="secondary-button" :data-testid="`grid-backup-up-${index}`" type="button" :disabled="index===0" @click="moveBackup(index,-1)">上移</button>
                  <button class="secondary-button" :data-testid="`grid-backup-down-${index}`" type="button" :disabled="index===backupCourts.length-1" @click="moveBackup(index,1)">下移</button>
                  <button class="text-button" :data-testid="`grid-remove-backup-${index}`" type="button" @click="removeBackup(index)">移除</button>
                </div>
              </li>
            </ol>
          </div>
          <div class="grid-selection-actions">
            <button class="secondary-button" data-testid="grid-clear" type="button" :disabled="!selectedRows.size&&!backupCourts.length" @click="clearSelection">清空选择</button>
            <button class="primary-button" data-testid="grid-apply" type="button" :disabled="!selection.valid||readOnlyGrid||loadedSignature!==signature" @click="applySelection">预览并应用到意向</button>
          </div>
        </div>
      </template>
    </template>
  </section>
</template>

<style scoped>
.venue-time-grid{display:grid;gap:16px;margin-top:8px;min-width:0}.grid-heading{display:flex;align-items:center;justify-content:space-between;gap:16px}.grid-heading h3,.grid-heading p{margin:0}.grid-source-badge{flex:0 0 auto;padding:8px 8px;border-radius:999px;background:var(--warning-soft);color:var(--warning);font-size:12px;font-weight:650}.grid-notice{margin:0;padding:16px 16px;border-radius:8px;background:var(--warning-soft);color:var(--warning);line-height:1.65}.grid-load-controls{display:flex;align-items:end;gap:16px;flex-wrap:wrap}.grid-load-controls>.field{flex:1 1 190px}.grid-load-controls>.secondary-button{min-height:var(--control-height)}.grid-manual-labels{margin:0;line-height:1.65}.grid-legend{display:flex;flex-wrap:wrap;gap:8px}.grid-legend-item{display:inline-flex;align-items:center;min-height:32px;padding:8px 8px;border-radius:8px;font-size:12px;line-height:1.35}.grid-scroll{width:100%;max-width:100%;overflow:auto;border:1px solid var(--line);border-radius:8px;overscroll-behavior-inline:contain}.venue-grid-table{width:max-content;min-width:100%;border-collapse:separate;border-spacing:0;background:var(--surface)}.venue-grid-table th,.venue-grid-table td{min-width:118px;padding:8px;border-right:1px solid var(--line);border-bottom:1px solid var(--line);text-align:center}.venue-grid-table thead th{position:sticky;top:0;z-index:2;background:var(--page);font-size:13px}.venue-grid-table thead th:first-child{left:0;z-index:3;min-width:104px}.venue-grid-table tbody th{position:sticky;left:0;z-index:1;background:var(--page);font-size:12px;white-space:nowrap}.venue-grid-table th small{display:block;margin-top:8px;color:var(--muted);font-size:10px;font-weight:500}.grid-cell{display:grid;place-items:center;gap:8px;width:100%;min-height:56px;padding:8px 8px;border:1px solid transparent;border-radius:8px;font-size:11px;line-height:1.35;cursor:pointer;white-space:normal}.grid-cell:disabled{cursor:not-allowed;opacity:.88}.grid-cell:focus-visible{outline:3px solid var(--brand);outline-offset:1px}.grid-cell small{font-size:10px}.state-selectable{background:var(--brand-soft);color:var(--brand-dark)}.grid-cell.state-selectable:hover{border-color:var(--brand)}.grid-cell.is-selected{background:var(--action);color:var(--on-accent);border-color:var(--action-hover)}.state-reserved,.state-historical_reserved{background:var(--danger-soft);color:var(--danger)}.state-activity_occupied,.state-historical_activity_occupied{background:var(--warning-soft);color:var(--warning)}.state-unbookable,.state-historical_unbookable{background:var(--page);color:var(--muted)}.state-unknown,.state-historical_unknown,.state-historical_selectable{background:repeating-linear-gradient(135deg,var(--page),var(--page) 6px,var(--surface) 6px,var(--surface) 12px);color:var(--muted)}.grid-selection-summary{display:grid;gap:8px}.grid-selection-summary p{margin:0}.grid-nonconcurrent{font-weight:650;color:var(--brand-dark)}.grid-backup-editor{display:grid;gap:8px;padding:16px;border:1px solid var(--line);border-radius:8px}.grid-backup-add-row{display:flex;align-items:center;justify-content:space-between;gap:8px;flex-wrap:wrap}.grid-backup-list{margin:0;padding-left:24px;display:grid;gap:8px}.grid-backup-list li{padding-left:8px}.grid-backup-actions{display:flex;flex-wrap:wrap;gap:8px;margin-top:8px}.grid-selection-actions{display:flex;gap:8px;flex-wrap:wrap}.grid-selection-actions button,.grid-backup-actions button,.grid-backup-add-row button{min-height:var(--control-height)}@media(max-width:600px){.venue-time-grid{padding:16px}.grid-load-controls>.secondary-button{width:100%}.venue-grid-table th,.venue-grid-table td{min-width:108px;padding:8px}.venue-grid-table thead th:first-child{min-width:94px}.grid-cell{min-height:56px;padding:8px;font-size:10px}.grid-selection-actions button{flex:1 1 140px}.grid-backup-actions button{flex:1 1 95px}}
</style>
