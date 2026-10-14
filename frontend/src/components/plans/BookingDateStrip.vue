<script setup>
import { computed } from 'vue';
import AppIcon from '../AppIcon.vue';
const props=defineProps({state:{type:Object,default:null},modelValue:{type:String,default:''},busy:Boolean});
const emit=defineEmits(['update:modelValue','refresh']);
const dates=computed(()=>(props.state?.queryable_target_dates||[]).slice(0,3));
function choose(date){if(date===props.modelValue)emit('refresh');else emit('update:modelValue',date);}
const labels=['今天','明天','后天'];
function weekday(value){return new Intl.DateTimeFormat('zh-CN',{weekday:'short',timeZone:'UTC'}).format(new Date(`${value}T12:00:00Z`));}
</script>
<template>
 <section class="booking-date-strip" aria-label="人工查看日期">
  <p v-if="!state" class="muted" role="status">正在读取日期…</p>
  <div class="date-strip-options">
   <button v-for="(date,index) in dates" :key="date" type="button" :data-testid="`browse-date-${index}`" :aria-pressed="modelValue===date" :disabled="busy" :title="`${date} ${weekday(date)}${index===2?'（默认）':''}`" @click="choose(date)"><span>{{ labels[index] }}</span><strong>{{ date.slice(5).replace('-','/') }}</strong></button>
   <label class="more-date" :title="state?.business_timezone_name"><AppIcon name="calendar" /><input data-testid="browse-more-date" type="date" aria-label="更多查看日期" :value="modelValue" :disabled="busy || !state" @input="choose($event.target.value)" /></label>
   <slot name="actions" />
  </div>
 </section>
</template>
<style scoped>
.booking-date-strip{min-width:0;padding:16px 20px;border-bottom:1px solid var(--line)}.date-strip-options{display:flex;align-items:center;gap:8px;flex-wrap:wrap}.date-strip-options>button[data-testid^="browse-date-"]{display:flex;align-items:center;gap:8px;min-height:44px;padding:10px 16px;border:1px solid var(--line);border-radius:8px;background:var(--surface);color:var(--ink);font:inherit;cursor:pointer}.date-strip-options>button[data-testid^="browse-date-"][aria-pressed=true]{background:var(--brand-dark);border-color:var(--brand-dark);color:var(--surface)}.date-strip-options>button[data-testid^="browse-date-"] strong{font-size:14px}.date-strip-options>button[data-testid^="browse-date-"]>span{font-size:14px}.more-date{display:flex;align-items:center;gap:8px;min-width:0;margin-left:auto;color:var(--muted)}.more-date input{width:155px;min-height:44px;border:1px solid var(--line);border-radius:8px;padding:8px;background:var(--surface);color:var(--ink);font:inherit;font-size:14px}@media(max-width:600px){.booking-date-strip{padding:12px}.date-strip-options{gap:6px}.date-strip-options>button[data-testid^="browse-date-"]{flex:1;justify-content:center;padding:8px 6px;gap:5px}.more-date{margin-left:0;flex:1 1 155px;min-width:155px;justify-content:flex-end}.more-date input{width:155px}}
</style>
