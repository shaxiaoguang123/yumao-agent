<script setup>
import { nextTick, useTemplateRef } from 'vue';
const props=defineProps({modelValue:{type:String,default:'manual'},planCount:{type:Number,default:0}});
const emit=defineEmits(['update:modelValue']);
const nav=useTemplateRef('nav');
const tabs=[{id:'manual',label:'人工预约',detail:'看时段 · 整理意向'},{id:'agent',label:'Agent 预约',detail:'对话补充 · 确认提案'},{id:'current',label:'当前计划',detail:'查看版本 · 匹配预览'}];
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
  <button v-for="(tab,index) in tabs" :id="`plan-tab-${tab.id}`" :key="tab.id" type="button" role="tab" :data-testid="`plan-tab-${tab.id}`" :aria-selected="modelValue===tab.id" :aria-controls="`plan-panel-${tab.id}`" :tabindex="modelValue===tab.id?0:-1" @click="emit('update:modelValue',tab.id)" @keydown="navigate($event,index)"><span class="tab-title">{{ tab.label }}<span v-if="tab.id==='current'" class="tab-count">{{ planCount }}</span></span><small>{{ tab.detail }}</small></button>
 </nav>
</template>
<style scoped>
.plan-section-tabs{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:8px;padding:6px;background:var(--surface);border:1px solid var(--line);border-radius:14px;margin:0 0 22px}.plan-section-tabs button{min-width:0;min-height:76px;padding:12px 16px;border:0;border-radius:10px;background:transparent;color:var(--muted);text-align:left;font:inherit;cursor:pointer}.plan-section-tabs button[aria-selected=true]{background:var(--brand-soft);color:var(--brand-dark);box-shadow:inset 0 0 0 1px var(--brand)}.plan-section-tabs button:hover{background:var(--page)}.plan-section-tabs button[aria-selected=true]:hover{background:var(--brand-soft)}.tab-title{display:flex;align-items:center;gap:8px;font-weight:700}.tab-count{padding:1px 7px;border-radius:999px;background:var(--page);font-size:12px}.plan-section-tabs small{display:block;margin-top:5px;font-size:13px;line-height:1.4}@media(max-width:600px){.plan-section-tabs{gap:4px;padding:4px}.plan-section-tabs button{padding:10px 8px;min-height:68px}.tab-title{font-size:14px;gap:4px}.plan-section-tabs small{font-size:11px}.tab-count{padding:1px 5px}}
</style>
