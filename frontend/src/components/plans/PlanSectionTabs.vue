<script setup>
import { nextTick, useTemplateRef } from 'vue';
import AppIcon from '../AppIcon.vue';
const props=defineProps({modelValue:{type:String,default:'query'},planCount:{type:Number,default:0}});
const emit=defineEmits(['update:modelValue']);
const nav=useTemplateRef('nav');
const tabs=[{id:'query',label:'查询场地',icon:'search'},{id:'manual',label:'选择预约',icon:'court'},{id:'agent',label:'Agent 预约',icon:'bot'},{id:'current',label:'抢票计划',icon:'list'}];
async function navigate(event,index){
 let next=index;
 if(event.key==='ArrowRight')next=(index+1)%tabs.length;
 else if(event.key==='ArrowLeft')next=(index+tabs.length-1)%tabs.length;
 else if(event.key==='Home')next=0;
 else if(event.key==='End')next=tabs.length-1;
 else return;
 event.preventDefault();emit('update:modelValue',tabs[next].id);await nextTick();nav.value?.querySelectorAll('[role="tab"]')[next]?.focus();
}
</script>
<template>
 <nav ref="nav" class="plan-section-tabs" role="tablist" aria-label="预约计划功能">
  <button v-for="(tab,index) in tabs" :id="`plan-tab-${tab.id}`" :key="tab.id" type="button" role="tab" :data-testid="`plan-tab-${tab.id}`" :aria-selected="modelValue===tab.id" :aria-controls="`plan-panel-${tab.id}`" :tabindex="modelValue===tab.id?0:-1" @click="emit('update:modelValue',tab.id)" @keydown="navigate($event,index)"><AppIcon :name="tab.icon" /><span class="tab-title">{{ tab.label }}<span v-if="tab.id==='current'" class="tab-count">{{ planCount }}</span></span></button>
 </nav>
</template>
<style scoped>
.plan-section-tabs{display:flex;gap:8px;border-bottom:1px solid var(--line);margin:0 0 16px}.plan-section-tabs button{display:flex;align-items:center;justify-content:center;gap:8px;min-width:0;min-height:var(--control-height);padding:8px 16px;border:0;border-bottom:2px solid transparent;background:transparent;color:var(--muted);font:inherit;cursor:pointer}.plan-section-tabs button[aria-selected=true]{color:var(--brand-dark);border-bottom-color:var(--brand)}.plan-section-tabs button:hover{background:var(--brand-soft)}.tab-title{display:flex;align-items:center;gap:8px;font-weight:650}.tab-count{padding:8px 8px;border-radius:999px;background:var(--brand-soft);font-size:12px}@media(max-width:600px){.plan-section-tabs button{flex:1;padding:8px 8px;gap:8px}.tab-title{font-size:13px;gap:8px}.plan-section-tabs .app-icon{width:17px;height:17px}.tab-count{padding:8px 8px}}
</style>
<style scoped>
@media(max-width:600px){.plan-section-tabs{overflow-x:auto;overscroll-behavior-inline:contain;scrollbar-width:none}.plan-section-tabs::-webkit-scrollbar{display:none}.plan-section-tabs button{flex:0 0 auto;min-width:112px;padding:8px 12px;gap:6px}.plan-section-tabs .app-icon{display:block;width:16px;height:16px}.tab-title{font-size:12px;gap:6px;white-space:nowrap}.tab-count{padding:4px 7px;font-size:11px}}
</style>
