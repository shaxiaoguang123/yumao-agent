<script setup>
import { minorToDecimal } from '../../utils/planForm.js';
defineProps({ result: { type: Object, required: true } });
const priceLabel=price=>price?`${minorToDecimal(price.total_minor,price.minor_unit_exponent)} ${price.currency_code}`:'价格未确认';
const backupLabel=flags=>[
  flags.lower_priority_time?'使用后续时间偏好':'',flags.lower_priority_court?'使用备选场地偏好':'',
  flags.other_court?'使用同场馆其他场地':'',flags.time_shift?'使用授权时间浮动':'',
].filter(Boolean).join('；')||'首选时间与场地';
</script>

<template>
  <section class="simulation-results" aria-label="模拟匹配结果">
    <h3>模拟匹配结果 · 计划版本 {{ result.base_version }}</h3>
    <p class="muted">{{ result.source.target_date }} · {{ result.source.timezone_name }} · 合成数据（未核验）</p>
    <p class="muted">{{ result.scope_note }}</p>
    <p v-if="!result.candidates.length" class="no-candidates" role="status">没有符合当前计划的候选时段。</p>
    <ol v-else class="match-candidates" aria-label="按偏好排序的候选时段">
      <li v-for="candidate in result.candidates" :key="`${candidate.court_name}-${candidate.start_time}`" data-testid="match-candidate" class="match-card">
        <div class="candidate-heading"><strong>第 {{ candidate.rank }} 顺位 · {{ candidate.court_name }}</strong><span class="candidate-price">模拟总价：{{ priceLabel(candidate.price) }}</span></div>
        <p class="candidate-time">{{ candidate.start_time }}～{{ candidate.end_time }} · {{ candidate.duration_minutes }} 分钟</p>
        <p class="candidate-backup">{{ backupLabel(candidate.fallback) }}</p>
        <ul class="candidate-reasons"><li v-for="(reason,index) in candidate.match_reasons" :key="index">{{ reason }}</li></ul>
      </li>
    </ol>
    <p v-if="result.candidates_truncated" class="muted">共 {{ result.total_candidates }} 个候选，当前展示前 {{ result.candidates.length }} 个。</p>
    <details v-if="result.reason_summary.length" :open="!result.candidates.length" class="match-diagnostics">
      <summary>未匹配原因</summary>
      <ul><li v-for="reason in result.reason_summary" :key="reason.code">{{ reason.message }}（{{ reason.count }} 项）</li></ul>
    </details>
    <p class="muted">排序：首选开始时间顺序 → 场地偏好顺序 → 浮动距离 → 稳定时间/名称顺序。价格用于预算筛选。</p>
    <p class="match-safety">候选建议未预订，不授予预约、支付或创建任务的权限。</p>
  </section>
</template>

<style scoped>
.simulation-results{display:grid;gap:12px;min-width:0}.simulation-results h3,.simulation-results p{margin:0}.match-candidates{list-style:none;padding:0;margin:0;display:grid;gap:12px}.match-card{padding:16px;border:1px solid var(--line);border-radius:10px;background:var(--surface);min-width:0}.candidate-heading{display:flex;justify-content:space-between;gap:10px;flex-wrap:wrap;overflow-wrap:anywhere}.candidate-price{color:var(--brand-dark)}.candidate-time{padding-top:9px;font-weight:600}.candidate-backup{padding-top:6px;color:var(--muted)}.candidate-reasons{margin:10px 0 0;padding-left:20px;color:var(--muted);font-size:13px;line-height:1.7}.match-diagnostics summary{cursor:pointer;font-weight:600}.match-diagnostics ul{padding-left:20px;line-height:1.7}.no-candidates,.match-safety{padding:12px;border-radius:8px;background:var(--brand-soft);color:var(--brand-dark)}
</style>
