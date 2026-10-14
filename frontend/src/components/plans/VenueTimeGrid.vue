<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue';

const props=defineProps({
  api:{type:Object,required:true},
  targetDate:{type:String,required:true},
  durationMinutes:{type:Number,required:true},
  venuePreference:{type:String,default:''},
  courtPreferences:{type:Array,default:()=>[]},
});
const emit=defineEmits(['update:targetDate','apply']);
const enabled=ref(false),optionsLoading=ref(true),optionsError=ref('');
const grid=ref(null),gridLoading=ref(false),gridError=ref(''),selected=ref(new Set());
const signature=computed(()=>JSON.stringify({
  target_date:props.targetDate,duration_minutes:props.durationMinutes,
  venue_preference:props.venuePreference,court_preferences:props.courtPreferences,
}));
let alive=true,optionsEpoch=0,gridEpoch=0,loadedSignature='';

const stateLabels={
  selectable:'可选择（合成）',reserved:'已预订（合成）',
  activity_occupied:'活动占用（合成）',unbookable:'不可预订（合成）',unknown:'未知（不可选择）',
};
const knownStates=new Set(Object.keys(stateLabels));
const canLoad=computed(()=>Boolean(props.targetDate&&props.venuePreference.trim()&&props.courtPreferences.length));
function syntheticReplyError(result,request){
  if(result?.grid_version!=='venue-time-grid-v1'||result?.simulation!==true
      ||result?.source?.source!=='synthetic-grid-v1'||result?.source?.data_state!=='synthetic'
      ||result?.source?.trust_state!=='synthetic'||result?.venue?.verification!=='unverified_manual'
      ||['can_query_upstream','can_book','can_pay','can_create_job'].some(key=>result?.[key]!==false))
    return '数据来源不是明确标记的合成网格，已停止展示。';
  if(result.target_date!==request.target_date||result.duration_minutes!==request.duration_minutes
      ||result.venue?.display_name!==request.venue_preference||result.atom_minutes!==30)
    return '网格数据与当前表单不一致，已停止展示；请重新读取。';
  if(!Array.isArray(result.courts)||JSON.stringify(result.courts.map(court=>court.display_name))!==JSON.stringify(request.court_preferences)
      ||result.courts.some(court=>court.verification!=='unverified_manual'))
    return '网格场地标签与当前人工偏好不一致，已停止展示。';
  if(!Array.isArray(result.rows)||!result.rows.length||!result.rows.every(row=>Array.isArray(row.cells)
      &&row.cells.length===result.courts.length&&row.cells.every(cell=>knownStates.has(cell.state)&&cell.selectable===(cell.state==='selectable'))))
    return '网格状态数据不完整或含未知格式，已停止展示。';
  return '';
}

async function loadOptions(){
  const epoch=++optionsEpoch;optionsLoading.value=true;optionsError.value='';
  try{
    const result=await props.api.options();
    if(!alive||epoch!==optionsEpoch)return;
    enabled.value=result.grid_preview_enabled===true;
  }catch{
    if(alive&&epoch===optionsEpoch){enabled.value=false;optionsError.value='模拟网格状态读取失败。';}
  }finally{if(alive&&epoch===optionsEpoch)optionsLoading.value=false;}
}

function invalidateGrid(){gridEpoch++;grid.value=null;selected.value=new Set();gridError.value='';loadedSignature='';}
watch(signature,(next)=>{if(loadedSignature&&next!==loadedSignature)invalidateGrid();});

async function loadGrid(){
  if(!enabled.value||optionsLoading.value||gridLoading.value)return;
  if(!canLoad.value){gridError.value='请先填写目标日期、人工场馆描述和至少一个人工场地偏好。';return;}
  const epoch=++gridEpoch,requestSignature=signature.value;
  gridLoading.value=true;gridError.value='';grid.value=null;selected.value=new Set();
  try{
    const request={
      target_date:props.targetDate,duration_minutes:props.durationMinutes,
      venue_preference:props.venuePreference,court_preferences:[...props.courtPreferences],
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
function isSelected(rowIndex,courtIndex){return selected.value.has(keyFor(rowIndex,courtIndex));}
function cellAriaLabel(row,court,cell,chosen){
  return `${court.display_name} ${row.start_time}到${row.end_time}：${chosen?'已选择':stateLabels[cell.state]}${cell.category_label?`，${cell.category_label}`:''}`;
}
function toggleCell(rowIndex,courtIndex,cell){
  if(!cell?.selectable||!grid.value)return;
  const next=new Set(selected.value),key=keyFor(rowIndex,courtIndex);
  if(next.has(key))next.delete(key);else next.add(key);
  selected.value=next;
}
function clearSelection(){selected.value=new Set();}

const selection=computed(()=>{
  if(!grid.value||!selected.value.size)return {hasSelection:false,valid:false,message:''};
  const rowsByCourt=new Map();
  for(const key of selected.value){
    const [rowIndex,courtIndex]=key.split(':').map(Number);
    if(!Number.isInteger(rowIndex)||!Number.isInteger(courtIndex)||!grid.value.rows[rowIndex]?.cells[courtIndex]?.selectable)
      return {hasSelection:true,valid:false,message:'所选格子已失效，请重新选择。'};
    if(!rowsByCourt.has(courtIndex))rowsByCourt.set(courtIndex,[]);
    rowsByCourt.get(courtIndex).push(rowIndex);
  }
  const requiredRows=grid.value.duration_minutes/grid.value.atom_minutes;
  let commonRows=null;
  for(const rows of rowsByCourt.values()){
    rows.sort((a,b)=>a-b);
    if(rows.length!==requiredRows)return {hasSelection:true,valid:false,message:`每个候选场地需选择连续的 ${requiredRows} 个时间格。`};
    if(rows.some((value,index)=>index>0&&value!==rows[index-1]+1))
      return {hasSelection:true,valid:false,message:'时间格必须连续，断档不能组成一个意向时段。'};
    if(commonRows&&rows.some((value,index)=>value!==commonRows[index]))
      return {hasSelection:true,valid:false,message:'多个场地必须选择完全相同的连续时间段，避免扩大计划偏好组合。'};
    commonRows=rows;
  }
  const first=grid.value.rows[commonRows[0]],last=grid.value.rows[commonRows.at(-1)];
  if(!first||!last||first.start_time>=last.end_time)
    return {hasSelection:true,valid:false,message:'无法从当前网格解析完整的连续时段。'};
  const courtIndexes=[...rowsByCourt.keys()].sort((a,b)=>a-b);
  return {
    hasSelection:true,valid:true,startTime:first.start_time,endTime:last.end_time,
    durationMinutes:grid.value.duration_minutes,
    courtNames:courtIndexes.map(index=>grid.value.courts[index].display_name),
    message:`${first.start_time}～${last.end_time} · ${grid.value.duration_minutes} 分钟`,
  };
});

function applySelection(){
  if(!selection.value.valid||!grid.value)return;
  emit('apply',{
    target_date:grid.value.target_date,start_time:selection.value.startTime,
    duration_minutes:selection.value.durationMinutes,court_preferences:[...selection.value.courtNames],
  });
}

onMounted(()=>void loadOptions());
onBeforeUnmount(()=>{alive=false;optionsEpoch++;gridEpoch++;});
</script>

<template>
  <section class="panel venue-time-grid" data-testid="venue-time-grid" aria-labelledby="venue-grid-title">
    <div class="grid-heading">
      <div><p class="eyebrow">人工意向网格</p><h3 id="venue-grid-title">选择场地与连续时间</h3></div>
      <span class="grid-source-badge">合成数据</span>
    </div>
    <p class="grid-notice">{{ grid?.notice||'网格中的可选、预订、活动占用与不可预订状态全部来自合成示例，并非真实场馆库存。选择只会整理意向，不会查询、预约或支付。' }}</p>
    <p v-if="optionsLoading" class="muted" role="status">正在读取网格能力…</p>
    <p v-else-if="optionsError" class="form-error" role="alert">{{ optionsError }} <button class="secondary-button" type="button" @click="loadOptions">重试</button></p>
    <p v-else-if="!enabled" class="muted" role="status">当前环境未启用模拟网格；手动时间和场地偏好仍可使用。</p>
    <template v-else>
      <div class="grid-load-controls">
        <label class="field">网格预览日期（同步计划）<input data-testid="grid-date" type="date" :value="targetDate" @input="emit('update:targetDate',$event.target.value)" /></label>
        <button class="secondary-button" data-testid="grid-load" type="button" :disabled="gridLoading||!canLoad" @click="loadGrid">{{ gridLoading?'正在生成…':'生成模拟网格' }}</button>
      </div>
      <p v-if="!canLoad" class="muted" role="status">填写目标日期、人工场馆描述和至少一个场地偏好后，才能查看对应的合成示例。</p>
      <p class="muted grid-manual-labels">场馆与列标题取自当前手工偏好，仅作合成场景标签；每格为 {{ grid?.atom_minutes||30 }} 分钟，不代表真实上游时间粒度。</p>
      <p v-if="gridError" class="form-error" role="alert">{{ gridError }}</p>
      <template v-if="grid">
        <div class="grid-legend" aria-label="网格状态图例">
          <span v-for="state in ['selectable','reserved','activity_occupied','unbookable','unknown']" :key="state" class="grid-legend-item" :class="`state-${state}`">{{ stateLabels[state] }}</span>
        </div>
        <div class="grid-scroll" role="region" aria-label="合成场地时间网格" tabindex="0">
          <table class="venue-grid-table">
            <thead><tr><th scope="col">时间</th><th v-for="court in grid.courts" :key="court.display_name" scope="col">{{ court.display_name }}<small>人工偏好</small></th></tr></thead>
            <tbody>
              <tr v-for="(row,rowIndex) in grid.rows" :key="row.start_time">
                <th scope="row">{{ row.start_time }}～{{ row.end_time }}</th>
                <td v-for="(cell,courtIndex) in row.cells" :key="grid.courts[courtIndex].display_name">
                  <button :data-testid="`grid-cell-${rowIndex}-${courtIndex}`" class="grid-cell" :class="[`state-${cell.state}`,{'is-selected':isSelected(rowIndex,courtIndex)}]" type="button" :disabled="!cell.selectable||gridLoading" :aria-pressed="isSelected(rowIndex,courtIndex)" :aria-label="cellAriaLabel(row,grid.courts[courtIndex],cell,isSelected(rowIndex,courtIndex))" @click="toggleCell(rowIndex,courtIndex,cell)">
                    {{ isSelected(rowIndex,courtIndex)?'已选择':stateLabels[cell.state] }}<small v-if="cell.category_label">{{ cell.category_label }}</small>
                  </button>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
        <div class="grid-selection-summary">
          <p v-if="selection.valid" role="status">当前选择：{{ selection.message }} · {{ selection.courtNames.join('、') }}</p>
          <p v-else-if="selection.hasSelection" class="form-error" role="status">{{ selection.message }}</p>
          <p v-else class="muted" role="status">点选连续的可选格子；多个场地必须选中完全相同的时段。</p>
          <div class="grid-selection-actions">
            <button class="secondary-button" data-testid="grid-clear" type="button" :disabled="!selected.size" @click="clearSelection">清空选择</button>
            <button class="primary-button" data-testid="grid-apply" type="button" :disabled="!selection.valid" @click="applySelection">预览并应用到意向</button>
          </div>
        </div>
      </template>
    </template>
  </section>
</template>

<style scoped>
.venue-time-grid{display:grid;gap:14px;margin-top:4px;min-width:0}
.grid-heading{display:flex;align-items:center;justify-content:space-between;gap:12px}
.grid-heading h3,.grid-heading p{margin:0}
.grid-source-badge{flex:0 0 auto;padding:5px 9px;border-radius:999px;background:var(--warning-soft);color:var(--warning);font-size:12px;font-weight:650}
.grid-notice{margin:0;padding:12px 14px;border-radius:10px;background:var(--warning-soft);color:var(--warning);line-height:1.65}
.grid-load-controls{display:flex;align-items:end;gap:12px;flex-wrap:wrap}
.grid-load-controls>.field{flex:1 1 190px}
.grid-load-controls>.secondary-button{min-height:44px}
.grid-manual-labels{margin:0}
.grid-legend{display:flex;flex-wrap:wrap;gap:8px}
.grid-legend-item{display:inline-flex;align-items:center;min-height:30px;padding:4px 8px;border-radius:7px;font-size:12px;line-height:1.35}
.grid-scroll{width:100%;max-width:100%;overflow:auto;border:1px solid var(--line);border-radius:10px;overscroll-behavior-inline:contain}
.venue-grid-table{width:max-content;min-width:100%;border-collapse:separate;border-spacing:0;background:var(--surface)}
.venue-grid-table th,.venue-grid-table td{min-width:118px;padding:8px;border-right:1px solid var(--line);border-bottom:1px solid var(--line);text-align:center}
.venue-grid-table thead th{position:sticky;top:0;z-index:2;background:var(--page);font-size:13px}
.venue-grid-table thead th:first-child{left:0;z-index:3;min-width:104px}
.venue-grid-table tbody th{position:sticky;left:0;z-index:1;background:var(--page);font-size:12px;white-space:nowrap}
.venue-grid-table th small{display:block;margin-top:4px;color:var(--muted);font-size:10px;font-weight:500}
.grid-cell{display:grid;place-items:center;gap:2px;width:100%;min-height:54px;padding:6px 8px;border:1px solid transparent;border-radius:8px;font-size:11px;line-height:1.35;cursor:pointer;white-space:normal}
.grid-cell:disabled{cursor:not-allowed;opacity:.88}
.grid-cell:focus-visible{outline:3px solid var(--brand);outline-offset:1px}
.grid-cell small{font-size:10px}
.state-selectable{background:var(--brand-soft);color:var(--brand-dark)}
.grid-cell.state-selectable:hover{border-color:var(--brand)}
.grid-cell.is-selected{background:var(--brand);color:#fff;border-color:var(--brand-dark)}
.state-reserved{background:var(--danger-soft);color:var(--danger)}
.state-activity_occupied{background:#fff1df;color:#7d4a13}
.state-unbookable{background:#edf0ed;color:#6e7974}
.state-unknown{background:repeating-linear-gradient(135deg,#f2f3f2,#f2f3f2 6px,#e5e8e5 6px,#e5e8e5 12px);color:#58655e}
.grid-selection-summary{display:grid;gap:8px}
.grid-selection-summary p{margin:0}
.grid-selection-actions{display:flex;gap:10px;flex-wrap:wrap}
.grid-selection-actions button{min-height:44px}
@media(max-width:600px){
  .venue-time-grid{padding:16px}
  .grid-load-controls>.secondary-button{width:100%}
  .venue-grid-table th,.venue-grid-table td{min-width:108px;padding:6px}
  .venue-grid-table thead th:first-child{min-width:94px}
  .grid-cell{min-height:58px;padding:5px;font-size:10px}
  .grid-selection-actions button{flex:1 1 140px}
}
</style>
