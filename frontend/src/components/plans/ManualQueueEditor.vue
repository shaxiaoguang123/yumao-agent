<script setup>
import { computed, ref } from 'vue';
import AppIcon from '../AppIcon.vue';
import { queueEntries } from '../../composables/useManualQueue.js';
const props=defineProps({queue:{type:Object,required:true},courtNames:{type:Array,default:()=>[]},busy:Boolean,error:String});
const emit=defineEmits(['save','cancel']);
const entries=ref(queueEntries(props.queue));
const names=computed(()=>[...new Set([...props.courtNames,...entries.value.map(e=>e.court_preference)])]);
function end(entry){const hour=Number(entry.start_time.slice(0,2))+entry.duration_minutes/60;return `${String(hour).padStart(2,'0')}:00`;}
function move(index,delta){const next=index+delta;if(next<0||next>=entries.value.length||entries.value[index].duration_minutes!==entries.value[next].duration_minutes)return;[entries.value[index],entries.value[next]]=[entries.value[next],entries.value[index]];}
function submit(){emit('save',entries.value.map(e=>({...e,end_time:end(e)})));}
</script>
<template>
 <form class="queue-editor" aria-label="编辑候选队列" @submit.prevent="submit">
  <div class="queue-editor-rows"><div v-for="(entry,index) in entries" :key="index" class="queue-editor-row"><span>{{ entry.duration_minutes===120?'两小时':'一小时' }} · {{ index+1 }}</span><select v-model="entry.court_preference" :aria-label="`候选${index+1}场地`" :disabled="busy"><option v-for="name in names" :key="name" :value="name">{{ name }}</option></select><select v-model="entry.start_time" :aria-label="`候选${index+1}开始时间`" :disabled="busy"><option v-for="h in 25-entry.duration_minutes/60" :key="h-1" :value="`${String(h-1).padStart(2,'0')}:00`">{{ String(h-1).padStart(2,'0') }}:00</option></select><span>→ {{ end(entry) }}</span><button type="button" :disabled="busy||index===0||entries[index-1]?.duration_minutes!==entry.duration_minutes" :aria-label="`编辑候选${index+1}上移`" @click="move(index,-1)"><AppIcon name="up" /></button><button type="button" :disabled="busy||index===entries.length-1||entries[index+1]?.duration_minutes!==entry.duration_minutes" :aria-label="`编辑候选${index+1}下移`" @click="move(index,1)"><AppIcon name="down" /></button><button type="button" :disabled="busy" :aria-label="`编辑移除候选${index+1}`" @click="entries.splice(index,1)"><AppIcon name="close" /></button></div></div>
  <p v-if="error" class="form-error" role="alert">{{ error }}</p><div class="queue-editor-actions"><button class="primary-button" type="submit" :disabled="busy">{{ busy?'保存中…':'保存修改' }}</button><button class="secondary-button" type="button" :disabled="busy" @click="emit('cancel')">取消</button></div>
 </form>
</template>
<style scoped>
.queue-editor{padding:8px;background:var(--page);border-radius:8px;margin:8px 0}.queue-editor-rows{max-height:340px;overflow:auto}.queue-editor-row{display:flex;align-items:center;gap:8px;flex-wrap:wrap;padding:8px 0;font-size:12px}.queue-editor-row select{min-height:var(--control-height);min-width:85px;border:1px solid var(--line);border-radius:8px;background:var(--surface);color:var(--ink);padding:8px}.queue-editor-row button{display:grid;place-items:center;min-width:36px;min-height:var(--control-height);border:0;background:transparent;color:var(--muted);cursor:pointer}.queue-editor-row button:disabled{opacity:.4}.queue-editor-actions{display:flex;gap:8px;margin-top:8px}.queue-editor-actions button{min-height:var(--control-height);font-size:13px}@media(max-width:600px){.queue-editor-row select,.queue-editor-row button{min-height:var(--control-height)}.queue-editor-row button{min-width:44px}}
</style>
