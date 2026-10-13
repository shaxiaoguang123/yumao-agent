<script setup>
import { computed } from 'vue';
const props=defineProps({state:{type:Object,default:null},modelValue:{type:String,default:''},busy:Boolean});
const emit=defineEmits(['update:modelValue']);
const dates=computed(()=>(props.state?.queryable_target_dates||[]).slice(0,3));
const labels=['今天','明天','后天'];
function weekday(value){return new Intl.DateTimeFormat('zh-CN',{weekday:'short',timeZone:'UTC'}).format(new Date(`${value}T12:00:00Z`));}
</script>
<template>
 <section class="booking-date-strip" aria-label="人工查看日期">
  <div class="date-strip-heading"><div><h2>选择查看日期</h2><p>{{ state ? `业务日期 ${state.business_date} · ${state.business_timezone_name}` : '正在读取服务端日期窗口…' }}</p></div><span class="date-default-hint">默认查看第三天（后天）</span></div>
  <div class="date-strip-options">
   <button v-for="(date,index) in dates" :key="date" type="button" :data-testid="`browse-date-${index}`" :aria-pressed="modelValue===date" :disabled="busy" @click="emit('update:modelValue',date)"><span>{{ labels[index] }}<small v-if="index===2">默认</small></span><strong>{{ date.slice(5).replace('-','月') }}日</strong><span class="date-weekday">{{ weekday(date) }}</span></button>
   <label class="more-date">更多日期<input data-testid="browse-more-date" type="date" aria-label="更多查看日期" :value="modelValue" :disabled="busy || !state" @input="emit('update:modelValue',$event.target.value)" /><small>窗口外可整理意向，不能查询实时状态</small></label>
  </div>
 </section>
</template>
<style scoped>
.booking-date-strip{padding:20px;background:var(--surface);border:1px solid var(--line);border-radius:14px;margin-bottom:18px;min-width:0}.date-strip-heading{display:flex;justify-content:space-between;align-items:center;gap:12px;flex-wrap:wrap;margin-bottom:16px}.date-strip-heading h2{font-size:18px;margin:0 0 6px}.date-strip-heading p{font-size:13px;color:var(--muted);margin:0}.date-default-hint{color:var(--brand-dark);background:var(--brand-soft);border-radius:6px;padding:6px 9px;font-size:12px}.date-strip-options{display:grid;grid-template-columns:repeat(3,minmax(0,1fr)) minmax(180px,1.4fr);gap:10px}.date-strip-options button{display:grid;gap:6px;min-height:96px;padding:12px;border:1px solid var(--line);border-radius:10px;background:var(--page);color:var(--ink);font:inherit;cursor:pointer;text-align:left}.date-strip-options button[aria-pressed=true]{background:var(--brand-dark);border-color:var(--brand-dark);color:var(--surface)}.date-strip-options button strong{font-size:20px}.date-strip-options button>span{font-size:13px}.date-strip-options button small{margin-left:8px;font-size:11px}.date-weekday{opacity:.8}.more-date{display:grid;align-content:center;gap:6px;min-width:0;padding:4px 0 4px 12px;font-size:13px}.more-date input{width:100%;min-width:0;min-height:44px;border:1px solid var(--line);border-radius:8px;padding:8px;background:var(--surface);color:var(--ink);font:inherit}.more-date small{color:var(--muted);font-size:12px;line-height:1.5}@media(max-width:600px){.booking-date-strip{padding:16px}.date-strip-options{grid-template-columns:repeat(3,minmax(0,1fr));gap:6px}.date-strip-options button{padding:10px 8px;min-height:90px}.date-strip-options button strong{font-size:17px}.date-strip-options button small{display:none}.more-date{grid-column:1/-1;padding:10px 0 0}.date-default-hint{font-size:11px}}
</style>
