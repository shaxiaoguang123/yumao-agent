<script setup>
import { toRef } from 'vue';
import { useAvailabilitySimulation } from '../../composables/useAvailabilitySimulation.js';
import AvailabilityMatchResults from './AvailabilityMatchResults.vue';
const props=defineProps({plans:{type:Array,default:()=>[]},api:{type:Object,required:true},session:{type:Object,required:true}});
const emit=defineEmits(['refresh-request']);
const {options,optionsError,loadingOptions,planId,scenario,result,error,busy,canMatch,loadOptions,match}=useAvailabilitySimulation(props.api,props.session,toRef(props,'plans'));
</script>

<template>
  <section class="panel availability-simulation" aria-labelledby="availability-simulation-title">
    <div><p class="eyebrow">合成数据演示</p><h2 id="availability-simulation-title">模拟匹配时段</h2></div>
    <p class="simulation-notice">当前为模拟时段匹配，使用合成数据，并非真实场馆库存，不会自动预约或支付。</p>
    <p v-if="loadingOptions" class="muted" role="status">正在读取模拟场景…</p>
    <p v-if="optionsError" class="form-error" role="alert">{{ optionsError }} <button class="secondary-button" type="button" @click="loadOptions">重新读取场景</button></p>
    <p v-if="options&&!options.enabled" class="muted">本环境未启用模拟匹配，手动计划和 AI 助手仍可使用。</p>
    <template v-if="options?.enabled">
      <p v-if="!plans.length" class="muted">请先生成预约意向并确认保存，再选择计划进行模拟。</p>
      <div class="simulation-controls">
        <label class="field">已保存的计划<select v-model="planId" data-testid="simulation-plan" :disabled="busy"><option value="">请选择预约计划</option><option v-for="plan in plans" :key="plan.plan_id" :value="plan.plan_id">{{ plan.intent.venue_preference }} · {{ plan.intent.target_date }} · 版本 {{ plan.version }}</option></select></label>
        <label class="field">合成场景<select v-model="scenario" data-testid="simulation-scenario" :disabled="busy"><option v-for="item in options.scenarios" :key="item.id" :value="item.id">{{ item.name }}</option></select></label>
      </div>
      <p class="muted">{{ options.scenarios.find(item=>item.id===scenario)?.description }} 人工场馆和场地名称仅作演示标签。</p>
      <div class="simulation-actions"><button class="primary-button" data-testid="simulate-matches" type="button" :disabled="!canMatch" @click="match">{{ busy?'正在匹配…':'模拟匹配时段' }}</button><button v-if="error" class="secondary-button" type="button" @click="emit('refresh-request')">刷新计划列表</button></div>
      <p v-if="error" class="form-error" role="alert">{{ error }}</p>
      <AvailabilityMatchResults v-if="result" :result="result" />
    </template>
  </section>
</template>

<style scoped>
.availability-simulation{display:grid;gap:16px;margin-top:22px}.availability-simulation h2{margin:0}.availability-simulation>p{margin:0}.simulation-notice{padding:14px;border-radius:10px;background:var(--warning-soft);color:var(--warning);line-height:1.7}.simulation-controls{display:grid;grid-template-columns:minmax(0,2fr) minmax(0,1fr);gap:16px}.simulation-actions{display:flex;gap:12px;flex-wrap:wrap}@media(max-width:700px){.simulation-controls{grid-template-columns:1fr}}
</style>
