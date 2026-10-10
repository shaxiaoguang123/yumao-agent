<script setup>
import { minorToDecimal } from '../../utils/planForm.js';
defineProps({snapshot:{type:Object,required:true}});
</script>
<template>
 <dl class="plan-facts">
  <dt>目标日期 / 时区</dt><dd>{{ snapshot.intent.target_date }} · {{ snapshot.context.timezone_name }}</dd>
  <dt>开始时间优先顺序</dt><dd>{{ snapshot.intent.preferred_start_times.join(' → ') }} · {{ snapshot.intent.duration_minutes }} 分钟</dd>
  <dt>人工场馆偏好</dt><dd>{{ snapshot.intent.venue_preference }}</dd>
  <dt>人工场地偏好</dt><dd>{{ snapshot.intent.court_preferences.join(' → ') || '未指定具体场地' }}</dd>
  <dt>备用意愿</dt><dd>{{ snapshot.intent.fallback_policy.allow_any_court_in_venue ? '愿意考虑同场馆其他场地' : '仅考虑填写的场地偏好' }}；{{ snapshot.intent.fallback_policy.allow_time_shift ? `开始时间可浮动 ${snapshot.intent.fallback_policy.allowed_start_time_range.start}～${snapshot.intent.fallback_policy.allowed_start_time_range.end}` : '开始时间不浮动' }}</dd>
  <dt>意向价格上限</dt><dd>{{ snapshot.intent.price_ceiling_minor === null ? '未设置' : `${minorToDecimal(snapshot.intent.price_ceiling_minor,snapshot.context.currency_minor_unit_exponent)} ${snapshot.context.currency_code}` }}</dd>
  <dt>核验状态</dt><dd>未经核验的人工偏好 · 尚未关联可信场馆目录</dd>
 </dl>
</template>
<style scoped>
.plan-facts{display:grid;grid-template-columns:minmax(120px,1fr) minmax(0,3fr);gap:10px 18px;margin:18px 0;line-height:1.7}.plan-facts dt{color:var(--muted)}.plan-facts dd{margin:0;overflow-wrap:anywhere}@media(max-width:600px){.plan-facts{grid-template-columns:1fr;gap:4px}.plan-facts dd{margin-bottom:8px}}
</style>
