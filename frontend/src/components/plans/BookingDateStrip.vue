<script setup>
import { computed } from 'vue';
import AppIcon from '../AppIcon.vue';
// Show one useful date beyond the three-day strip: the selected custom date,
// or (when viewing the short window) the first later date with a saved queue.
const props=defineProps({state:{type:Object,default:null},modelValue:{type:String,default:''},busy:Boolean,extraDate:{type:String,default:''}});
const emit=defineEmits(['update:modelValue','refresh']);
const dates=computed(()=>(props.state?.queryable_target_dates||[]).slice(0,3));
const extraDate=computed(()=>{
 const selected=props.modelValue;
 if(selected&&!dates.value.includes(selected))return selected;
 const candidate=props.extraDate;
 return candidate&&candidate>=(dates.value.at(-1)||'')&&!dates.value.includes(candidate)?candidate:'';
});
function choose(date){if(date===props.modelValue)emit('refresh');else emit('update:modelValue',date);}
function weekday(value){return new Intl.DateTimeFormat('zh-CN',{weekday:'short',timeZone:'UTC'}).format(new Date(`${value}T12:00:00Z`));}
function monthDay(value){return value.slice(5).replace('-','/')}
</script>
<template>
 <section class="booking-date-strip" aria-label="预约日期">
  <p v-if="!props.state" class="muted" role="status">正在读取日期…</p>
  <div class="date-strip-options">
   <button v-for="(date,index) in dates" :key="date" type="button" :data-testid="`browse-date-${index}`" :aria-pressed="props.modelValue===date" :disabled="props.busy" :title="`${date} ${weekday(date)}${index===2?'（默认）':''}`" @click="choose(date)"><span>{{ weekday(date) }}</span><strong>{{ monthDay(date) }}</strong></button>
   <button v-if="extraDate" type="button" class="extra-date-button" data-testid="browse-date-extra" :aria-pressed="props.modelValue===extraDate" :disabled="props.busy" :title="`${extraDate} ${weekday(extraDate)}`" @click="choose(extraDate)"><span>{{ weekday(extraDate) }}</span><strong>{{ monthDay(extraDate) }}</strong></button>
   <label class="more-date" :title="props.state?.business_timezone_name"><AppIcon name="calendar" /><input data-testid="browse-more-date" type="date" aria-label="更多查看日期" :value="props.modelValue" :disabled="props.busy || !props.state" @input="choose($event.target.value)" /></label>
   <slot name="actions" />
  </div>
 </section>
</template>
<style scoped>
.booking-date-strip{min-width:0;padding:16px 16px;border-bottom:1px solid var(--line)}.date-strip-options{display:flex;align-items:center;gap:8px;flex-wrap:wrap}.date-strip-options>button[data-testid^="browse-date-"]{display:flex;align-items:center;gap:8px;min-height:var(--control-height);padding:8px 16px;border:1px solid var(--line);border-radius:12px;background:var(--surface);color:var(--ink);font:inherit;cursor:pointer}.date-strip-options>button[data-testid^="browse-date-"][aria-pressed=true]{background:var(--brand-dark);border-color:var(--brand-dark);color:var(--surface)}.date-strip-options>button[data-testid^="browse-date-"] strong{font-size:14px}.date-strip-options>button[data-testid^="browse-date-"]>span{font-size:14px}.more-date{display:flex;align-items:center;gap:8px;min-width:0;margin-left:auto;color:var(--muted)}.more-date input{width:155px;min-height:var(--control-height);border:1px solid var(--line);border-radius:12px;padding:8px;background:var(--surface);color:var(--ink);font:inherit;font-size:14px}@media(max-width:600px){.booking-date-strip{padding:16px}.date-strip-options{gap:8px}.date-strip-options>button[data-testid^="browse-date-"]{flex:1;justify-content:center;padding:8px 8px;gap:8px}.more-date{margin-left:0;flex:1 1 155px;min-width:155px;justify-content:flex-end}.more-date input{width:155px}}
.booking-date-strip{padding:12px 16px}.date-strip-options>button[data-testid^="browse-date-"]>span{font-size:12px;white-space:nowrap}.date-strip-options>button[data-testid^="browse-date-"] strong{font-weight:600;white-space:nowrap}
@media(max-width:600px){.booking-date-strip{padding:10px}.date-strip-options{gap:6px}.date-strip-options>button[data-testid^="browse-date-"]{min-width:64px;gap:4px}.more-date>.app-icon{display:none}.more-date input{min-width:0;width:100%;font-size:14px}.more-date{flex:1 1 140px;min-width:0;max-width:165px}}
</style>
