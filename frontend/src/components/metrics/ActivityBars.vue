<script setup>
import { computed } from 'vue';
const props = defineProps({ rows: { type: Array, required: true }, kind: { type: String, default: 'execution' } });
const legend = computed(() => props.kind === 'errors'
  ? [{ key: 'error', label: '错误', color: 'var(--danger)' }, { key: 'warning', label: '警告', color: 'var(--warning)' }]
  : [{ key: 'succeeded', label: '成功', color: 'var(--success)' }, { key: 'failed', label: '失败', color: 'var(--danger)' }, { key: 'needs_attention', label: '待处理', color: 'var(--warning)' }, { key: 'other', label: '其他状态', color: 'var(--brand)' }]);
const maximum = computed(() => Math.max(1, ...props.rows.map(row => legend.value.reduce((sum, item) => sum + (row[item.key] || 0), 0))));
const bars = computed(() => props.rows.map(row => ({
  date: row.date, label: row.date.slice(5).replace('-', '/'),
  total: legend.value.reduce((sum, item) => sum + (row[item.key] || 0), 0),
  description: `${row.date}，${legend.value.map(item => `${item.label} ${row[item.key] || 0}`).join('，')}`,
  segments: legend.value.map(item => ({ ...item, count: row[item.key] || 0, height: `${(row[item.key] || 0) / maximum.value * 100}%` })),
})));
</script>
<template>
  <div class="activity-chart">
    <ul class="chart-legend" aria-label="图例"><li v-for="item in legend" :key="item.key"><i :style="{ background: item.color }" aria-hidden="true" />{{ item.label }}</li></ul>
    <ol class="activity-bars" :aria-label="kind === 'errors' ? '近七天警告与错误数量' : '近七天执行任务状态'">
      <li v-for="bar in bars" :key="bar.date" :aria-label="bar.description" :title="bar.description" tabindex="0">
        <span class="bar-value" aria-hidden="true">{{ bar.total }}</span>
        <div class="bar-track" aria-hidden="true"><span v-for="segment in bar.segments" :key="segment.key" :style="{ height: segment.height, background: segment.color }" /></div>
        <span class="bar-label" aria-hidden="true">{{ bar.label }}</span>
      </li>
    </ol>
  </div>
</template>
<style scoped>
.activity-chart{min-width:0}.chart-legend{display:flex;gap:12px;flex-wrap:wrap;padding:0;margin:0 0 16px;list-style:none;color:var(--muted);font-size:12px}.chart-legend li{display:flex;align-items:center;gap:5px}.chart-legend i{width:8px;height:8px;border-radius:3px}.activity-bars{display:grid;grid-template-columns:repeat(7,minmax(0,1fr));gap:12px;list-style:none;padding:0;margin:0}.activity-bars li{display:grid;gap:6px;min-width:0;text-align:center;border-radius:8px}.bar-track{height:100px;display:flex;flex-direction:column-reverse;align-items:stretch;border-bottom:1px solid var(--line);background:var(--page);border-radius:5px 5px 0 0;overflow:hidden}.bar-track span{display:block;flex-shrink:0}.bar-value{font-size:12px;font-variant-numeric:tabular-nums;color:var(--ink)}.bar-label{color:var(--muted);font-size:11px}.activity-bars li:focus-visible{outline:2px solid var(--brand);outline-offset:3px}@media(max-width:500px){.activity-bars{gap:8px}.bar-track{height:80px}}
</style>
