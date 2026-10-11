<script setup>
import { computed, nextTick, ref, shallowRef, useTemplateRef, watch } from 'vue';
import { copy, decimalToMinor, minorToDecimal } from '../../utils/planForm.js';
import VenueTimeGrid from './VenueTimeGrid.vue';
const props=defineProps({source:{type:Object,required:true},busy:Boolean,saveBlocked:Boolean,fields:{type:Object,default:()=>({})},gridApi:{type:Object,default:null},sessionKey:{type:String,default:''}});
const emit=defineEmits(['save','cancel','target-change','draft-change']);
const form=ref(copy(props.source.intent)), courtsText=shallowRef(''), priceText=shallowRef(''), localError=shallowRef('');
const rangeStart=shallowRef(''), rangeEnd=shallowRef('');
const pendingGridSelection=ref(null),gridReviewMessage=shallowRef('');
const currentCourts=computed(()=>courtsText.value.split('\n').map(value=>value.trim()).filter(Boolean));
const summary=useTemplateRef('errorSummary');
watch(()=>props.source,source=>{
 const restored=source.draftState;
 if(restored){form.value=copy(restored.form);courtsText.value=restored.courtsText;priceText.value=restored.priceText;rangeStart.value=restored.rangeStart;rangeEnd.value=restored.rangeEnd;}
 else{form.value=copy(source.intent);courtsText.value=form.value.court_preferences.join('\n');priceText.value=minorToDecimal(form.value.price_ceiling_minor,source.context.currency_minor_unit_exponent);rangeStart.value=form.value.fallback_policy.allowed_start_time_range?.start||'';rangeEnd.value=form.value.fallback_policy.allowed_start_time_range?.end||'';}
 localError.value='';pendingGridSelection.value=null;gridReviewMessage.value='';
},{immediate:true,flush:'sync'});
watch(()=>form.value.target_date,date=>{pendingGridSelection.value=null;emit('target-change',date);},{immediate:true});
const gridContextKey=computed(()=>JSON.stringify({
 source_plan:props.source.planId,base_version:props.source.baseVersion,session:props.sessionKey,blocked:props.saveBlocked,
 target_date:form.value.target_date,preferred_start_times:form.value.preferred_start_times,
 duration_minutes:form.value.duration_minutes,venue_preference:form.value.venue_preference,
 court_preferences:courtsText.value,fallback_policy:form.value.fallback_policy,range_start:rangeStart.value,range_end:rangeEnd.value,
 price:priceText.value,
}));
function currentDraftState(){return {form:copy(form.value),courtsText:courtsText.value,priceText:priceText.value,rangeStart:rangeStart.value,rangeEnd:rangeEnd.value};}
watch(gridContextKey,()=>{
 emit('draft-change',currentDraftState());
 if(pendingGridSelection.value){pendingGridSelection.value=null;gridReviewMessage.value='表单内容已变化，请重新生成并确认网格选择。';}
},{flush:'sync'});
watch(()=>props.fields,async()=>{if(Object.keys(props.fields).length){await nextTick();summary.value?.focus();}});
function moveTime(index,delta){const times=form.value.preferred_start_times;[times[index],times[index+delta]]=[times[index+delta],times[index]];}
function reviewGridSelection(selection){
 if(props.busy||props.saveBlocked)return;
 pendingGridSelection.value={...selection,mode:'strict',previous:{target_date:form.value.target_date,preferred_start_times:[...form.value.preferred_start_times],duration_minutes:form.value.duration_minutes,court_preferences:[...currentCourts.value],fallback_policy:currentFallback(),price:priceText.value}};
 gridReviewMessage.value='';
}
function cancelGridSelection(){pendingGridSelection.value=null;}
function currentFallback(){
 return {allow_any_court_in_venue:form.value.fallback_policy.allow_any_court_in_venue,
  allow_time_shift:form.value.fallback_policy.allow_time_shift,
  allowed_start_time_range:form.value.fallback_policy.allow_time_shift?{start:rangeStart.value,end:rangeEnd.value}:null};
}
const proposedFallback=computed(()=>pendingGridSelection.value?.mode==='preserve'
 ? copy(pendingGridSelection.value.previous.fallback_policy)
 : {allow_any_court_in_venue:false,allow_time_shift:false,allowed_start_time_range:null});
function fallbackSummary(value){
 const courts=value.allow_any_court_in_venue?'允许考虑同场馆其他场地':'不扩展到其他场地';
 const time=value.allow_time_shift?`允许开始时间在 ${value.allowed_start_time_range?.start||'未填写'}～${value.allowed_start_time_range?.end||'未填写'} 浮动`:'不允许额外时间浮动';
 return `${courts}；${time}`;
}
function confirmGridSelection(){
 const selection=pendingGridSelection.value;if(!selection||props.busy||props.saveBlocked)return;
 const nextFallback=proposedFallback.value;
 pendingGridSelection.value=null;
 form.value.target_date=selection.target_date;
 form.value.duration_minutes=selection.duration_minutes;
 form.value.preferred_start_times=[selection.start_time];
 courtsText.value=selection.court_preferences.join('\n');
 form.value.fallback_policy=copy(nextFallback);
 rangeStart.value=nextFallback.allowed_start_time_range?.start||'';
 rangeEnd.value=nextFallback.allowed_start_time_range?.end||'';
 localError.value='';
 gridReviewMessage.value='';
}
async function submit(){
 if(props.busy||props.saveBlocked)return;
 localError.value='';
 try {
  const intent=copy(form.value);
  intent.court_preferences=courtsText.value.split('\n').map(s=>s.trim()).filter(Boolean);
  intent.price_ceiling_minor=decimalToMinor(priceText.value,props.source.context.currency_minor_unit_exponent);
  intent.fallback_policy.allowed_start_time_range=intent.fallback_policy.allow_time_shift ? {start:rangeStart.value,end:rangeEnd.value}:null;
  emit('save',intent);
 } catch(error){localError.value=error.message;await nextTick();summary.value?.focus();}
}
</script>
<template>
 <section class="panel plan-editor" aria-labelledby="plan-editor-title">
  <header class="plan-section-heading"><div><p class="eyebrow">人工意向 · 尚未核验</p><h2 id="plan-editor-title">{{ source.planId ? `编辑预约意向 · 版本 ${source.baseVersion}` : '新建预约意向' }}</h2></div></header>
  <p class="muted">时区 {{ source.context.timezone_name }}。场馆和场地均为未经核验的人工偏好。</p>
  <form class="form-stack" :aria-busy="busy" @submit.prevent="submit">
   <div v-if="localError || Object.keys(fields).length" ref="errorSummary" class="form-error" role="alert" tabindex="-1">
    <p v-if="localError">{{ localError }}</p>
    <p v-for="(error,field) in fields" :key="field"><a :href="`#plan-${field}`">{{ error }}</a></p>
   </div>
   <fieldset class="plan-fieldset" :disabled="busy">
    <div class="plan-two-columns">
     <label class="field">目标预约日期<input id="plan-target_date" v-model="form.target_date" name="target_date" type="date" required :aria-invalid="Boolean(fields.target_date)" /><small v-if="fields.target_date" class="form-error">{{ fields.target_date }}</small></label>
     <label class="field">预约时长<select id="plan-duration_minutes" v-model.number="form.duration_minutes" name="duration_minutes" :aria-invalid="Boolean(fields.duration_minutes)"><option v-for="minutes in [30,60,90,120,150,180,210,240]" :key="minutes" :value="minutes">{{ minutes }} 分钟</option></select><small class="muted">这是意向时长，尚未确认上游支持情况。</small></label>
    </div>
    <div id="plan-preferred_start_times" class="form-stack">
     <h3>开始时间偏好</h3><p class="muted">按优先顺序保存，第一项是时间浮动的基准。最多 8 项。</p>
     <div v-for="(_time,index) in form.preferred_start_times" :key="index" class="plan-time-row">
      <label class="field">优先 {{ index+1 }}<input v-model="form.preferred_start_times[index]" :name="`start_time_${index}`" :aria-label="`优先 ${index+1} 开始时间`" type="time" required :aria-invalid="Boolean(fields.preferred_start_times)" /></label>
      <div class="plan-time-actions"><button class="secondary-button" type="button" :data-testid="`time-up-${index}`" :aria-label="`将时间 ${index+1} 提前`" :disabled="index===0" @click="moveTime(index,-1)">上移</button><button class="secondary-button" type="button" :aria-label="`将时间 ${index+1} 后移`" :disabled="index===form.preferred_start_times.length-1" @click="moveTime(index,1)">下移</button><button class="text-button" type="button" :aria-label="`移除时间 ${index+1}`" :disabled="form.preferred_start_times.length===1" @click="form.preferred_start_times.splice(index,1)">移除</button></div>
     </div>
     <small v-if="fields.preferred_start_times" class="form-error">{{ fields.preferred_start_times }}</small>
     <button data-testid="add-time" class="secondary-button" type="button" :disabled="form.preferred_start_times.length>=8" @click="form.preferred_start_times.push('')">添加开始时间</button>
    </div>
    <label class="field">场馆名称或描述（人工偏好）<input id="plan-venue_preference" v-model="form.venue_preference" name="venue_preference" maxlength="200" required :aria-invalid="Boolean(fields.venue_preference)" /><small v-if="fields.venue_preference" class="form-error">{{ fields.venue_preference }}</small></label>
    <label class="field">场地偏好（人工输入，每行一项）<textarea id="plan-court_preferences" v-model="courtsText" name="court_preferences" rows="3" :aria-invalid="Boolean(fields.court_preferences)" /><small class="muted">最多 16 项，每项 100 字；顺序代表你的偏好，不关联上游场地 ID。</small><small v-if="fields.court_preferences" class="form-error">{{ fields.court_preferences }}</small></label>
    <VenueTimeGrid v-if="gridApi" :api="gridApi" :target-date="form.target_date" :duration-minutes="form.duration_minutes" :venue-preference="form.venue_preference" :court-preferences="currentCourts" :timezone-name="source.context.timezone_name" :selection-context-key="gridContextKey" @update:target-date="form.target_date=$event" @apply="reviewGridSelection" />
    <p v-if="gridReviewMessage" class="form-error" role="status">{{ gridReviewMessage }}</p>
    <section v-if="pendingGridSelection" class="grid-apply-confirmation" data-testid="grid-apply-confirmation" aria-label="确认应用网格意向">
     <h3>确认应用网格意向</h3>
     <p class="muted">这只会更新下方未保存表单。点击“保存预约意向”后才会创建 PlanRevision；不会同时预约多块场地。</p>
     <dl>
      <dt>原日期／时间／时长</dt><dd>{{ pendingGridSelection.previous.target_date }} · {{ pendingGridSelection.previous.preferred_start_times.join(' → ') }} · {{ pendingGridSelection.previous.duration_minutes }} 分钟</dd>
      <dt>新日期／时间／时长</dt><dd>{{ pendingGridSelection.target_date }} · {{ pendingGridSelection.start_time }}～{{ pendingGridSelection.end_time }} · {{ pendingGridSelection.duration_minutes }} 分钟</dd>
      <dt>原场地顺序</dt><dd>{{ pendingGridSelection.previous.court_preferences.join(' → ')||'未填写场地' }}</dd>
      <dt>新场地顺序</dt><dd>{{ pendingGridSelection.court_preferences.join(' → ') }}</dd>
      <dt>原备用策略</dt><dd>原来允许同场馆其他场地：{{ pendingGridSelection.previous.fallback_policy.allow_any_court_in_venue?'是':'否' }}；原时间浮动：{{ pendingGridSelection.previous.fallback_policy.allow_time_shift?`${pendingGridSelection.previous.fallback_policy.allowed_start_time_range?.start||'未填写'}～${pendingGridSelection.previous.fallback_policy.allowed_start_time_range?.end||'未填写'}`:'关闭' }}</dd>
      <dt>拟保存备用策略</dt><dd data-testid="grid-proposed-fallback">{{ pendingGridSelection.mode==='preserve'?'拟保存保留原备用策略':'拟保存不允许额外场地或时间浮动' }} · {{ fallbackSummary(proposedFallback) }}</dd>
      <dt>原价格上限</dt><dd>{{ pendingGridSelection.previous.price||'未设置' }} {{ source.context.currency_code||'' }}；价格上限保持不变</dd>
      <dt>新价格上限</dt><dd>{{ pendingGridSelection.previous.price||'未设置' }} {{ source.context.currency_code||'' }}；不自动提高或取消</dd>
     </dl>
     <fieldset class="grid-mode-options" :disabled="busy">
      <legend>选择本次应用的备用范围</legend>
      <label class="plan-checkbox"><input v-model="pendingGridSelection.mode" data-testid="grid-mode-strict" type="radio" value="strict" />严格按照本次网格选择（默认）：只按已确认顺序尝试所选场地，不扩展场地，不浮动时间。</label>
      <label class="plan-checkbox"><input v-model="pendingGridSelection.mode" data-testid="grid-mode-preserve" type="radio" value="preserve" />保留原计划额外备用策略：{{ fallbackSummary(pendingGridSelection.previous.fallback_policy) }}</label>
     </fieldset>
     <div class="plan-actions"><button data-testid="confirm-grid-selection" class="primary-button" type="button" :disabled="busy||saveBlocked" @click="confirmGridSelection">确认应用到未保存表单</button><button data-testid="cancel-grid-selection" class="secondary-button" type="button" :disabled="busy" @click="cancelGridSelection">取消，不修改表单</button></div>
    </section>
    <div id="plan-fallback_policy" class="form-stack">
     <h3>基本备用策略</h3>
     <label class="plan-checkbox"><input v-model="form.fallback_policy.allow_any_court_in_venue" name="allow_any_court" type="checkbox" />愿意考虑同场馆其他场地（意愿尚未核验）</label>
     <label class="plan-checkbox"><input v-model="form.fallback_policy.allow_time_shift" name="allow_time_shift" type="checkbox" />允许开始时间在指定范围内浮动</label>
     <div v-if="form.fallback_policy.allow_time_shift" class="plan-two-columns"><label class="field">最早开始时间<input v-model="rangeStart" name="range_start" type="time" required /></label><label class="field">最晚开始时间<input v-model="rangeEnd" name="range_end" type="time" required /></label></div>
     <small v-if="fields.fallback_policy" class="form-error">{{ fields.fallback_policy }}</small>
    </div>
    <label v-if="source.context.currency_code" class="field">价格上限（{{ source.context.currency_code }}，可选）<input id="plan-price_ceiling_minor" v-model="priceText" name="price_ceiling" type="text" inputmode="decimal" maxlength="24" :aria-invalid="Boolean(fields.price_ceiling_minor)" /><small class="muted">保存的是意向金额上限，不代表报价或支付授权。</small><small v-if="fields.price_ceiling_minor" class="form-error">{{ fields.price_ceiling_minor }}</small></label>
    <p v-else class="muted">部署未配置货币，当前不能设置价格上限。</p>
   </fieldset>
   <div class="plan-actions"><button class="primary-button" data-testid="save-plan" type="submit" :disabled="busy || saveBlocked">{{ busy ? '正在保存…' : '保存预约意向' }}</button><button class="secondary-button" type="button" :disabled="busy" @click="emit('cancel')">关闭表单</button></div>
  </form>
 </section>
</template>
<style scoped>
.plan-fieldset{display:grid;gap:22px;border:0;padding:0;margin:0;min-width:0}.plan-two-columns{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:18px}.plan-time-row{display:flex;align-items:end;flex-wrap:wrap;gap:10px}.plan-time-row>.field{flex:1 1 130px}.plan-time-actions{display:flex;flex-wrap:wrap;gap:8px}.plan-checkbox{display:flex;align-items:center;gap:10px;min-height:44px;line-height:1.6}.plan-checkbox input{width:20px;height:20px;flex-shrink:0;accent-color:var(--brand)}.field textarea{width:100%;max-width:100%;padding:12px;border:1px solid var(--line);border-radius:10px;background:var(--surface);color:var(--ink);font:inherit;line-height:1.6;resize:vertical}.field textarea:focus-visible{outline:3px solid var(--brand);outline-offset:2px}.plan-actions{display:flex;flex-wrap:wrap;gap:10px}.grid-apply-confirmation{display:grid;gap:10px;padding:16px;border:1px solid var(--line);border-radius:12px;background:var(--brand-soft);min-width:0}.grid-apply-confirmation h3,.grid-apply-confirmation p{margin:0}.grid-apply-confirmation dl{display:grid;grid-template-columns:minmax(90px,auto) minmax(0,1fr);gap:6px 12px;margin:0}.grid-apply-confirmation dt{font-weight:650}.grid-apply-confirmation dd{margin:0;overflow-wrap:anywhere}@media(max-width:600px){.plan-two-columns{grid-template-columns:1fr}.plan-time-row{align-items:stretch}.plan-time-actions{width:100%}.grid-apply-confirmation dl{grid-template-columns:1fr;gap:2px}.grid-apply-confirmation dd{margin-bottom:8px}}
</style>
