<script setup>
defineProps({state:Object,error:String});
function formatInstant(ms,zone){return ms===null?'无可用日期边界':new Intl.DateTimeFormat('zh-CN',{timeZone:zone,dateStyle:'medium',timeStyle:'short',hourCycle:'h23'}).format(ms);}
</script>
<template>
 <aside class="plan-window" aria-label="日期窗口状态" aria-live="polite">
  <h3>日期窗口 · 服务器计算</h3>
  <p v-if="error" class="form-error">{{ error }}</p><p v-else-if="!state" class="muted">正在读取日期窗口…</p>
  <template v-else>
   <p class="plan-window-status">{{ state.can_query ? '当前处于日历可查询窗口' : '当前不可查询' }}</p>
   <p v-if="state.reason_code==='timezone_context_mismatch'">保存时区与当前业务时区不一致。请创建新计划以使用当前设置；历史日期和时间不会被重新解释。</p>
   <p class="muted">业务日期 {{ state.business_date }} · {{ state.business_timezone_name }}<br />日历窗口：{{ (state.queryable_target_dates||[]).join('、') }}</p>
   <p class="muted">T−2 查询边界：{{ formatInstant(state.query_open_at_utc_ms,state.business_timezone_name) }}<br />预计开放：{{ String(state.estimated_open_at_local||'未提供').replace('T',' ') }}（{{ state.business_timezone_name }}，未确认的估计，仅展示）</p>
   <p class="muted">未绑定草稿不会发送上游查询、预约或支付请求，不能创建执行任务。</p>
  </template>
 </aside>
</template>
<style scoped>
.plan-window{padding:20px;border:1px solid var(--line);border-radius:var(--radius);background:var(--brand-soft);margin:20px 0}.plan-window p{margin:10px 0 0}.plan-window-status{font-weight:700;color:var(--brand-dark)}
</style>
