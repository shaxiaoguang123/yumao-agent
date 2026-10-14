<script setup>
import { computed, ref } from 'vue';
import { candidateKey } from '../../composables/useManualQueue.js';
const props=defineProps({courtNames:{type:Array,default:()=>[]},entries:{type:Array,default:()=>[]},duration:{type:Number,default:120},disabled:Boolean});
const emit=defineEmits(['change']);
const from=ref(16),until=ref(22),error=ref('');
const courts=computed(()=>[...new Set([...props.courtNames,...props.entries.map(e=>e.court_preference)].filter(v=>typeof v==='string'&&v.trim()).map(v=>v.trim()))].slice(0,32));
const rows=computed(()=>Array.from({length:Math.max(0,until.value-from.value)},(_,index)=>({start:from.value+index,end:from.value+index+1})));
const clock=hour=>`${String(hour).padStart(2,'0')}:00`;
function selected(row,court){return props.entries.some(e=>e.duration_minutes===props.duration&&e.court_preference===court&&Number(e.start_time.slice(0,2))<=row.start&&Number(e.end_time.slice(0,2))>=row.end);}
function toggle(row,court){
 if(props.disabled)return;error.value='';
 const entry={court_preference:court,start_time:clock(row.start),end_time:clock(row.start+props.duration/60),duration_minutes:props.duration};
 const existing=props.entries.find(e=>candidateKey(e)===candidateKey(entry))||props.entries.find(e=>e.duration_minutes===props.duration&&e.court_preference===court&&e.start_time<=entry.start_time&&e.end_time>entry.start_time);
 if(existing){emit('change',props.entries.filter(e=>e!==existing));return;}
 if(row.start+props.duration/60>until.value||row.start+props.duration/60>24){error.value='两小时候选必须完整覆盖两个连续小时，请选择更早的开始格。';return;}
 if(props.entries.length>=32){error.value='候选最多 32 项，请先移除不需要的候选。';return;}
 emit('change',[...props.entries,entry]);
}
</script>
<template>
 <div class="manual-queue-grid">
  <div class="queue-grid-heading"><span>点击开始格 · {{ duration===120?'连续两小时':'一小时' }}</span><details class="queue-range"><summary>时间范围</summary><div><label>开始<select v-model.number="from" aria-label="网格开始小时"><option v-for="h in 24" :key="h-1" :value="h-1">{{ clock(h-1) }}</option></select></label><label>结束<select v-model.number="until" aria-label="网格结束小时"><option v-for="h in 24" :key="h" :value="h">{{ clock(h) }}</option></select></label></div></details></div>
  <p v-if="error" class="form-error" role="alert">{{ error }}</p>
  <p v-if="!courts.length" class="muted">先在“查询场地”读取场地名称，再选择预约偏好。</p>
  <div v-else class="queue-table-scroll" tabindex="0" aria-label="场地与时间偏好网格，可横向滚动"><table><thead><tr><th scope="col">时间</th><th v-for="court in courts" :key="court" scope="col">{{ court }}</th></tr></thead><tbody><tr v-for="(row,index) in rows" :key="row.start"><th scope="row">{{ clock(row.start) }}–{{ clock(row.end) }}</th><td v-for="(court,column) in courts" :key="court"><button type="button" class="queue-cell" :class="{'is-selected':selected(row,court)}" :data-testid="`queue-cell-${index}-${column}`" :aria-label="`${court} ${clock(row.start)}开始 ${duration===120?'两小时':'一小时'}候选`" :aria-pressed="selected(row,court)" :disabled="disabled" @click="toggle(row,court)"><span v-if="selected(row,court)">✓</span></button></td></tr></tbody></table></div>
 </div>
</template>
<style scoped>
.queue-grid-heading{display:flex;align-items:center;justify-content:space-between;gap:8px;font-size:12px;color:var(--muted);margin-bottom:10px}.queue-range{position:relative}.queue-range summary{cursor:pointer;min-height:32px;display:flex;align-items:center}.queue-range>div{position:absolute;right:0;z-index:4;display:flex;gap:8px;padding:10px;border:1px solid var(--line);background:var(--surface);border-radius:8px}.queue-range label{display:flex;gap:5px;align-items:center;white-space:nowrap}.queue-range select{min-height:40px}.queue-table-scroll{max-width:100%;overflow:auto;border:1px solid var(--line);border-radius:6px}.queue-table-scroll table{width:100%;border-collapse:separate;border-spacing:0;table-layout:fixed;min-width:700px}.queue-table-scroll th{padding:7px 4px;font-size:12px;text-align:center;background:var(--page);position:sticky;top:0;z-index:1}.queue-table-scroll tr>th:first-child{width:120px;position:sticky;left:0;z-index:2}.queue-table-scroll thead tr>th:first-child{z-index:3}.queue-table-scroll td{padding:3px;border-top:1px solid var(--line)}.queue-cell{width:100%;height:44px;border:1px solid var(--line);background:var(--surface);cursor:pointer;color:var(--brand);border-radius:4px}.queue-cell.is-selected{background:var(--brand-soft);border-color:var(--brand);box-shadow:inset 0 0 0 1px var(--brand)}.queue-cell:focus-visible{outline:2px solid var(--brand);outline-offset:1px}.queue-cell:disabled{cursor:default;opacity:.6}
</style>
