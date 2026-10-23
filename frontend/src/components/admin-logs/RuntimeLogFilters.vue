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
    </div>
    <details class="log-advanced"><summary>更多筛选</summary><div class="log-filter-grid">
      <label class="field">用户 ID<input v-model="filters.user_id" maxlength="128" placeholder="留空查看全部用户" /></label>

      <label class="field">请求编号<input v-model="filters.request_id" maxlength="128" spellcheck="false" /></label>
      <label class="field">会话编号<input v-model="filters.conversation_id" maxlength="128" spellcheck="false" /></label>
      <label class="field">执行任务编号<input v-model="filters.run_id" maxlength="128" spellcheck="false" /></label>
      <label class="field">错误码<input v-model="filters.code" maxlength="96" placeholder="例如 provider_timeout" spellcheck="false" /></label>
    </div></details>
    <div class="log-filter-actions"><button class="secondary-button" type="button" :disabled="busy" @click="reset">重置筛选</button><button class="primary-button" type="submit" :disabled="busy">查询日志</button></div>
  </form>
</template>
<style scoped>
.log-filter-form { display:grid; grid-template-columns:minmax(0,1fr) auto; gap:12px; align-items:end; }
.log-filter-grid { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:10px; }
.log-filter-grid .field { min-width:0; font-size:12px; }
.log-filter-grid input,.log-filter-grid select { width:100%; min-height:44px; }
.log-advanced { grid-column:1/-1; grid-row:2; }
.log-advanced > summary { display:flex; align-items:center; min-height:44px; color:var(--muted); cursor:pointer; font-size:13px; }
.log-advanced[open] .log-filter-grid { grid-template-columns:repeat(3,minmax(0,1fr)); padding-top:8px; }
.log-filter-actions { display:flex; align-items:center; gap:8px; grid-column:2; grid-row:1; }
@media(max-width:700px) { .log-filter-form { grid-template-columns:minmax(0,1fr); gap:6px; } .log-filter-actions { grid-row:2; grid-column:1; justify-content:flex-end; } .log-advanced { grid-row:3; } }
@media(max-width:380px) { .log-filter-grid,.log-advanced[open] .log-filter-grid { grid-template-columns:repeat(2,minmax(0,1fr)); } .log-filter-grid > .field:last-child { grid-column:1/-1; } }
</style>
