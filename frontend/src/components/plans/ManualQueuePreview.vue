<script setup>
import { computed } from 'vue';
import AppIcon from '../AppIcon.vue';
import { candidateKey } from '../../composables/useManualQueue.js';
const props=defineProps({entries:{type:Array,default:()=>[]},readonly:Boolean,disabled:Boolean});
const emit=defineEmits(['change']);
const groups=computed(()=>[120,60].map(duration=>({duration,label:duration===120?'两小时 · 优先':'一小时 · 随后',entries:props.entries.filter(e=>e.duration_minutes===duration)})));
function remove(entry){emit('change',props.entries.filter(e=>candidateKey(e)!==candidateKey(entry)));}
function move(group,index,delta){const next=[...group.entries];[next[index],next[index+delta]]=[next[index+delta],next[index]];emit('change',[...props.entries.filter(e=>e.duration_minutes!==group.duration),...next]);}
</script>
<template>
 <div class="queue-preview" aria-label="候选队列预览">
  <section v-for="group in groups" :key="group.duration" class="queue-group" :data-testid="`queue-${group.duration}`">
   <div class="queue-group-heading"><h3>{{ group.label }}</h3><span>{{ group.entries.length }}</span></div>
   <p v-if="!group.entries.length" class="queue-empty">尚未选择</p>
   <ol v-else tabindex="0" :aria-label="`${group.label}候选列表，可滚动`"><li v-for="(entry,index) in group.entries" :key="candidateKey(entry)"><span class="queue-rank">{{ index+1 }}</span><div class="queue-entry"><strong>{{ entry.court_preference }}</strong><span class="queue-scope">{{ entry.scope_label||'预约类别未绑定' }}</span><span>{{ entry.start_time }}–{{ entry.end_time }}</span></div><div v-if="!readonly" class="queue-entry-actions"><button type="button" :disabled="disabled||index===0" :aria-label="`将${group.duration}分钟候选${index+1}上移`" @click="move(group,index,-1)"><AppIcon name="up" /></button><button type="button" :disabled="disabled||index===group.entries.length-1" :aria-label="`将${group.duration}分钟候选${index+1}下移`" @click="move(group,index,1)"><AppIcon name="down" /></button><button type="button" :disabled="disabled" :aria-label="`移除${group.duration}分钟候选${index+1}`" @click="remove(entry)"><AppIcon name="close" /></button></div></li></ol>
  </section>
 </div>
</template>
<style scoped>
.queue-preview{display:grid;gap:16px;min-width:0}.queue-group{border:1px solid var(--line);border-radius:8px;overflow:hidden}.queue-group-heading{display:flex;align-items:center;justify-content:space-between;background:var(--page);padding:8px 16px}.queue-group-heading h3{font-size:14px;margin:0}.queue-group-heading>span{font-size:12px;color:var(--muted)}.queue-empty{font-size:13px;color:var(--muted);margin:16px}.queue-group ol{list-style:none;padding:0;margin:0;max-height:200px;overflow:auto;overscroll-behavior:contain;scrollbar-gutter:stable}.queue-group li{display:flex;gap:8px;align-items:center;padding:8px 8px;border-top:1px solid var(--line)}.queue-rank{font-size:12px;color:var(--brand);min-width:15px}.queue-entry{display:flex;flex:1;flex-direction:column;min-width:0;font-size:13px;gap:8px}.queue-entry strong{overflow-wrap:anywhere}.queue-entry span{color:var(--muted);white-space:nowrap}.queue-entry .queue-scope{font-size:12px;color:var(--muted)}.queue-entry-actions{display:flex;gap:8px}.queue-entry-actions button{display:grid;place-items:center;min-width:44px;min-height:var(--control-height);border:0;background:transparent;color:var(--muted);padding:8px;cursor:pointer;border-radius:8px}.queue-entry-actions button:hover:not(:disabled){background:var(--brand-soft)}.queue-entry-actions button:disabled{opacity:.35;cursor:default}
.queue-group{container-type:inline-size}
@container(max-width:280px){.queue-group li{display:grid;grid-template-columns:15px minmax(0,1fr);gap:4px 8px}.queue-entry{gap:4px}.queue-entry-actions{grid-column:2;justify-content:flex-end;gap:4px}}
</style>
