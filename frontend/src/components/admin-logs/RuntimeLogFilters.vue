<script setup>
import { reactive } from 'vue';
import { logModules } from '../../utils/runtimeLogs.js';
const emit = defineEmits(['apply']);
defineProps({ busy: Boolean });
const filters = reactive({ hours: '24', level: '', module: '', user_id: '', code: '', request_id: '', conversation_id: '', run_id: '' });
function submit() {
  emit('apply', Object.fromEntries(Object.entries(filters).map(([key, value]) => [key, String(value).trim()])));
}
function reset() {
  Object.assign(filters, { hours: '24', level: '', module: '', user_id: '', code: '', request_id: '', conversation_id: '', run_id: '' });
  submit();
}
</script>
<template>
  <form class="log-filter-form" role="search" aria-label="筛选运行日志" @submit.prevent="submit">
    <div class="log-filter-grid">
      <label class="field">时间范围<select v-model="filters.hours" aria-label="时间范围"><option value="1">近 1 小时</option><option value="24">近 24 小时</option><option value="168">近 7 天</option><option value="336">近 14 天</option></select></label>
      <label class="field">日志级别<select v-model="filters.level" aria-label="日志级别"><option value="">全部级别</option><option value="error">错误</option><option value="warning">警告</option><option value="info">信息</option></select></label>
      <label class="field">所属模块<select v-model="filters.module" aria-label="所属模块"><option value="">全部模块</option><option v-for="item in logModules" :key="item[0]" :value="item[0]">{{ item[1] }}</option></select></label>
      <label class="field">用户 ID<input v-model="filters.user_id" maxlength="128" placeholder="留空查看全部用户" /></label>
    </div>
    <details class="log-advanced"><summary>关联编号与错误码</summary><div class="log-filter-grid">
      <label class="field">请求编号<input v-model="filters.request_id" maxlength="128" spellcheck="false" /></label>
      <label class="field">会话编号<input v-model="filters.conversation_id" maxlength="128" spellcheck="false" /></label>
      <label class="field">执行任务编号<input v-model="filters.run_id" maxlength="128" spellcheck="false" /></label>
      <label class="field">错误码<input v-model="filters.code" maxlength="96" placeholder="例如 provider_timeout" spellcheck="false" /></label>
    </div></details>
    <div class="log-filter-actions"><p class="muted">编号与错误码按完整值匹配；时间显示为北京时间。</p><button class="secondary-button" type="button" :disabled="busy" @click="reset">重置筛选</button><button class="primary-button" type="submit" :disabled="busy">查询日志</button></div>
  </form>
</template>
<style scoped>
.log-filter-form{display:grid;gap:14px}.log-filter-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px}.log-filter-grid .field{margin:0;min-width:0;font-size:12px}.log-filter-grid input,.log-filter-grid select{width:100%;min-height:40px}.log-advanced summary{cursor:pointer;color:var(--muted);font-size:13px;padding:8px 0;min-height:40px}.log-advanced[open] .log-filter-grid{padding-top:10px}.log-filter-actions{display:flex;align-items:center;justify-content:flex-end;gap:10px;flex-wrap:wrap}.log-filter-actions p{flex:1 1 220px;font-size:12px;margin:0}.log-filter-actions button{min-height:40px}@media(max-width:850px){.log-filter-grid{grid-template-columns:repeat(2,minmax(0,1fr))}}@media(max-width:480px){.log-filter-grid{grid-template-columns:minmax(0,1fr)}.log-filter-actions p{flex-basis:100%}.log-filter-actions button{flex:1;min-height:44px}}
</style>
