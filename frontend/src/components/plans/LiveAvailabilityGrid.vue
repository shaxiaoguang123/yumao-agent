<script setup>
import { computed } from 'vue';
import AppIcon from '../AppIcon.vue';
const props = defineProps({ grid: { type: Object, required: true }, expired: Boolean });
const states = {
  observed_clear_unmarked: '未标记占用',
  observed_reserved: '已预订显示',
  observed_activity_occupied: '活动占用',
  observed_unbookable: '不可预订显示',
  observed_unknown: '状态未知',
};
const stateIcons = { observed_clear_unmarked: 'minus', observed_reserved: 'lock',
  observed_activity_occupied: 'ticket', observed_unbookable: 'close', observed_unknown: 'info' };
const observedTime = computed(() => new Intl.DateTimeFormat('zh-CN', {
  dateStyle: 'short', timeStyle: 'medium', timeZone: props.grid.timezone_name,
}).format(props.grid.source.captured_at_utc_ms));
</script>

<template>
  <section class="observation-grid" data-testid="live-availability-grid" aria-labelledby="live-grid-title">
    <header class="observation-heading"><div><h3 id="live-grid-title">{{ grid.query_scope.display_name }} · {{ grid.target_date }}</h3></div><span class="observation-badge">{{ expired ? '观察已过期' : '当前读取观察' }}</span></header>
    <p class="observation-notice"><AppIcon name="lock" />只读 · 未核验可预约性</p>
    <p class="muted observation-time">读取时间 {{ observedTime }}</p>
    <p v-if="expired" class="form-error" role="status" data-testid="live-grid-expired">观察已过期，请重新读取。</p>
    <div class="observation-legend" aria-label="官方观察显示状态"><span v-for="(label,state) in states" :key="state" :class="`cell-${state}`"><AppIcon :name="stateIcons[state]" />{{ label }}</span></div>
    <div class="observation-scroll" role="region" aria-label="官方场地时间网格，只读" tabindex="0">
      <table class="observation-table">
        <caption class="sr-only">官方场地时间网格，仅供查看</caption>
        <thead><tr><th scope="col">时间标签</th><th v-for="(court,index) in grid.courts" :key="index" scope="col">{{ court.display_name }}</th></tr></thead>
        <tbody><tr v-for="(row,rowIndex) in grid.rows" :key="rowIndex"><th scope="row">{{ row.time_label }}</th><template v-if="row.time_status_code === '0'"><td v-for="(cell,courtIndex) in row.cells" :key="courtIndex"><span class="observation-cell" :class="`cell-${cell.state}`" :title="cell.label || states[cell.state]" :aria-label="`${grid.courts[courtIndex].display_name} ${row.time_label}：${states[cell.state]}`"><AppIcon :name="stateIcons[cell.state]" /></span></td></template><td v-else :colspan="grid.courts.length" class="muted">{{ row.time_status_code === '1' ? '此时段未展示' : '状态未知' }}</td></tr></tbody>
      </table>
    </div>
    <details class="observation-source-details"><summary><AppIcon name="info" />数据来源</summary><p class="muted">{{ grid.notice }}</p><p class="muted">仅保留 60 秒显示新鲜度；这不是平台保证的库存有效期。价格单位尚未核验，金额已隐藏。“未标记占用”仅表示响应没有冲突标记。场馆归属、行标记业务含义和原子时长未核验，不能确认可预约；此观察不会参与 Matcher、保存计划或产生订单。</p></details>
  </section>
</template>

<style scoped>
.observation-grid{display:grid;grid-template-columns:minmax(0,1fr);gap:8px;min-width:0}.observation-heading{display:flex;justify-content:space-between;align-items:center;gap:12px;flex-wrap:wrap}.observation-heading h3,.observation-heading p{margin:0}.observation-badge{padding:6px 10px;border-radius:8px;background:var(--warning-soft);color:var(--warning);font-size:13px}.observation-notice{padding:12px 14px;background:var(--warning-soft);color:var(--warning);border-radius:10px;line-height:1.65;margin:0}.observation-legend{display:flex;gap:8px;flex-wrap:wrap}.observation-legend span{padding:6px 10px;border-radius:6px;font-size:13px}.observation-scroll{min-width:0;max-width:100%;overflow:auto;border:1px solid var(--line);border-radius:10px;overscroll-behavior-inline:contain}.observation-table{width:max-content;min-width:100%;border-collapse:separate;border-spacing:0;background:var(--surface)}.observation-table caption{padding:10px;text-align:left;color:var(--muted);font-size:13px}.observation-table th,.observation-table td{min-width:82px;padding:5px;border-right:1px solid var(--line);border-bottom:1px solid var(--line);text-align:center}.observation-table th{font-size:13px;background:var(--page)}.observation-table thead th{position:sticky;top:0;z-index:2}.observation-table th:first-child{position:sticky;left:0;z-index:1;min-width:70px}.observation-table thead th:first-child{z-index:3}.observation-table th small{display:block;margin-top:4px;font-size:11px;font-weight:400;color:var(--muted)}.observation-cell{display:grid;place-items:center;min-height:40px;padding:5px;border-radius:6px;font-size:12px;line-height:1.5}.cell-observed_clear_unmarked{background:var(--brand-soft);color:var(--brand-dark)}.cell-observed_reserved{background:var(--danger-soft);color:var(--danger)}.cell-observed_activity_occupied{background:var(--warning-soft);color:var(--warning)}.cell-observed_unbookable,.cell-observed_unknown{background:var(--page);color:var(--muted)}@media(max-width:600px){.observation-table th,.observation-table td{min-width:82px;padding:5px}.observation-table th:first-child{min-width:70px}.observation-cell{min-height:44px}}
.observation-heading h3{font-size:15px}.observation-heading .observation-badge{font-size:12px;padding:4px 7px}.observation-notice{display:flex;align-items:center;gap:5px;padding:0;background:none;font-size:12px}.observation-notice .app-icon{width:15px;height:15px}.observation-time{font-size:12px;margin:0}.observation-legend{gap:6px}.observation-legend span{display:flex;align-items:center;gap:4px;padding:3px 6px;font-size:12px}.observation-legend .app-icon{width:13px;height:13px}.observation-cell .app-icon{width:17px;height:17px}.observation-source-details{font-size:12px;color:var(--muted)}.observation-source-details summary{display:flex;align-items:center;gap:4px;cursor:pointer;min-height:30px;width:fit-content}.observation-source-details .app-icon{width:16px;height:16px}.observation-source-details p{line-height:1.6}
</style>
