<script setup>
import { onBeforeUnmount, ref, watch } from 'vue';
import HistoricalBookingGrid from './HistoricalBookingGrid.vue';

const props=defineProps({api:{type:Object,required:true},session:{type:Object,required:true}});
const enabled=ref(false),optionsLoading=ref(true),optionsError=ref('');
const preview=ref(null),previewLoading=ref(false),previewError=ref('');
const fileInput=ref(null);
const sessionKey=()=>`${props.session.status}:${props.session.user?.user_id||''}:${props.session.csrfToken||''}`;
let alive=true,epoch=0;

function authorized(){return props.session.status==='authenticated'&&Boolean(props.session.user?.user_id);}
function validPreview(value){
  if(value?.grid_version!=='official-history-grid-v1'||value?.simulation!==false
    ||value?.source?.data_state!=='historical_unverified'||value?.source?.trust_state!=='normalized_unverified'
    ||value?.source?.freshness_state!=='unknown'||value?.price_state!=='omitted_unit_unverified'
    ||['can_select','can_match','can_bind','can_query_upstream','can_book','can_pay','can_create_job'].some(key=>value?.[key]!==false)
    ||!Array.isArray(value?.courts)||!Array.isArray(value?.rows)||!value.rows.length)return false;
  if(value.courts.some(court=>Object.keys(court).sort().join(',')!=='display_name,verification'
    ||court.verification!=='historical_unverified'||typeof court.display_name!=='string'))return false;
  const states=new Set(['historical_selectable','historical_reserved','historical_activity_occupied','historical_unbookable','historical_unknown']);
  return value.rows.every(row=>typeof row.time_label==='string'
    &&row.time_status&&['recognized_unverified','unknown'].includes(row.time_status.state)
    &&(row.time_status.code===null||['0','1'].includes(row.time_status.code))
    &&Array.isArray(row.cells)&&row.cells.length===value.courts.length
    &&row.cells.every(cell=>Object.keys(cell).sort().join(',')==='category_label,reason_code,selectable,state'
      &&states.has(cell.state)&&cell.selectable===false&&cell.reason_code==='historical_unverified'));
}

async function loadOptions(generation,key){
  if(!authorized()){optionsLoading.value=false;enabled.value=false;return;}
  optionsLoading.value=true;optionsError.value='';
  try{
    const result=await props.api.options();
    if(!alive||generation!==epoch||key!==sessionKey())return;
    enabled.value=result.history_preview_enabled===true;
  }catch{
    if(alive&&generation===epoch&&key===sessionKey()){enabled.value=false;optionsError.value='历史预览能力读取失败。';}
  }finally{if(alive&&generation===epoch&&key===sessionKey())optionsLoading.value=false;}
}

watch(sessionKey,(next,previous)=>{
  if(next===previous)return;
  const generation=++epoch;
  preview.value=null;previewError.value='';previewLoading.value=false;enabled.value=false;
  if(fileInput.value)fileInput.value.value='';
  void loadOptions(generation,next);
},{immediate:true,flush:'sync'});

async function importResponse(event){
  const input=event.target,file=input.files?.[0];
  previewError.value='';
  if(!file)return;
  if(file.size>128*1024){previewError.value='响应文件超过 128 KiB，未发送或解析。';input.value='';return;}
  const generation=++epoch,key=sessionKey();
  previewLoading.value=true;
  try{
    let response;
    try{response=JSON.parse(await file.text());}
    catch{previewError.value='文件不是有效的 JSON 响应。';return;}
    if(!response||typeof response!=='object'||Array.isArray(response)){previewError.value='文件不是有效的 JSON 响应。';return;}
    const result=await props.api.historyPreview(response);
    if(!alive||generation!==epoch||key!==sessionKey())return;
    if(!validPreview(result)){previewError.value='响应结构不符合已核对的显示规则；内容未保存。';return;}
    preview.value=result;
  }catch{
    if(alive&&generation===epoch&&key===sessionKey())previewError.value='无法安全解析此历史响应；内容未保存，也未显示原始字段。';
  }finally{
    input.value='';
    if(alive&&generation===epoch&&key===sessionKey())previewLoading.value=false;
  }
}

onBeforeUnmount(()=>{alive=false;epoch++;preview.value=null;});
</script>

<template>
  <section v-if="optionsLoading||optionsError||enabled" class="panel official-history-preview" data-testid="official-history-preview" aria-labelledby="history-preview-title">
    <div><p class="eyebrow">本地文件 · 离线协议观察</p><h2 id="history-preview-title">官方历史时段只读预览</h2></div>
    <p class="history-preview-notice">仅解析你主动选择的官方响应 JSON；不读取抓包目录、不连接上游、不保存原始响应。预览不可选格、不可匹配，不会创建计划版本或任务。</p>
    <p v-if="optionsLoading" class="muted" role="status">正在读取本地预览能力…</p>
    <p v-else-if="optionsError" class="form-error" role="alert">{{ optionsError }}</p>
    <p v-else-if="!enabled" class="muted" role="status">当前环境未启用历史响应预览。</p>
    <template v-else>
      <label class="history-file-field">选择 JSON 响应文件<input ref="fileInput" data-testid="history-response-file" type="file" accept=".json,application/json" :disabled="previewLoading" @change="importResponse" /><small>选择包含 success、resultData 和 bookingByTime 字段的本地响应 JSON。文件内容只用于本次解析。</small></label>
      <p v-if="previewLoading" class="muted" role="status">正在校验并生成只读显示…</p>
      <p v-if="previewError" class="form-error" role="alert">{{ previewError }}</p>
      <HistoricalBookingGrid v-if="preview" :preview="preview" />
    </template>
  </section>
</template>

<style scoped>
.official-history-preview{display:grid;grid-template-columns:minmax(0,1fr);gap:16px;margin:24px 0 0;min-width:0}.official-history-preview h2{margin:0}.history-preview-notice{margin:0;padding:16px 16px;border-radius:8px;background:var(--warning-soft);color:var(--warning);line-height:1.65}.history-file-field{display:grid;grid-template-columns:minmax(0,1fr);gap:8px;padding:16px;border:1px dashed var(--line);border-radius:8px;line-height:1.5;min-width:0}.history-file-field input{width:100%;max-width:100%;min-width:0;font:inherit}.history-file-field small{color:var(--muted)}
</style>
