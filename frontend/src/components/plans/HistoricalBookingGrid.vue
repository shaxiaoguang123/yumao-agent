<script setup>
defineProps({preview:{type:Object,required:true}});

const labels={
  historical_selectable:'历史客户端显示可选（非实时）',
  historical_reserved:'历史客户端显示已预订',
  historical_activity_occupied:'历史客户端显示活动占用（类别未核验）',
  historical_unbookable:'历史客户端显示不可预订',
  historical_unknown:'未知状态',
};
</script>

<template>
  <section class="panel historical-grid" data-testid="historical-booking-grid" aria-labelledby="historical-grid-title">
    <div class="grid-heading"><div><p class="eyebrow">历史观察 · 只读</p><h3 id="historical-grid-title">官方场地时间显示</h3></div><span class="history-source-badge">非实时数据</span></div>
    <p class="historical-notice">{{ preview.notice }}</p>
    <p class="muted">场馆查询范围未知 · 采集日期未知 · 时区未知 · 价格单位未核验并已隐藏。历史可选状态不代表现在可预约。</p>
    <div class="historical-legend" aria-label="历史显示状态图例"><span v-for="state in Object.keys(labels)" :key="state" :class="`state-${state}`">{{ labels[state] }}</span></div>
    <div class="historical-scroll" role="region" aria-label="官方历史时间显示网格，只读" tabindex="0">
      <table class="historical-table">
        <thead><tr><th scope="col">官方时间标签</th><th v-for="(court,index) in preview.courts" :key="`${court.display_name}-${index}`" scope="col">{{ court.display_name }}<small>本次响应列 {{ index+1 }} · 未核验归属</small></th></tr></thead>
        <tbody>
          <tr v-for="(row,index) in preview.rows" :key="index">
            <th scope="row">{{ row.time_label }}<small v-if="row.time_status.state==='recognized_unverified'">官方行标记 {{ row.time_status.code }} · 含义未核验</small><small v-else>行标记未知</small></th>
            <template v-if="row.time_status.code==='0'"><td v-for="(cell,courtIndex) in row.cells" :key="`${index}-${courtIndex}`"><span class="historical-cell" :class="`state-${cell.state}`" :aria-label="`${preview.courts[courtIndex].display_name} ${row.time_label}：${labels[cell.state]||labels.historical_unknown}`">{{ labels[cell.state]||labels.historical_unknown }}</span></td></template>
            <td v-else :colspan="preview.courts.length">{{ row.time_status.code==='1'?'官方客户端此行不展示场地格子（业务含义未核验）':'未知行状态，不展示场地格子' }}</td>
          </tr>
        </tbody>
      </table>
    </div>
    <p class="muted historical-footer">此预览不生成 AvailabilitySnapshot，不交给匹配器，不绑定场馆，不会保存计划版本或创建任务。</p>
  </section>
</template>

<style scoped>
.historical-grid{display:grid;grid-template-columns:minmax(0,1fr);gap:14px;margin:20px 0 0;min-width:0}.grid-heading{display:flex;align-items:center;justify-content:space-between;gap:12px}.grid-heading h3,.grid-heading p{margin:0}.history-source-badge{flex:0 0 auto;padding:5px 9px;border-radius:999px;background:var(--warning-soft);color:var(--warning);font-size:12px;font-weight:650}.historical-notice{margin:0;padding:12px 14px;border-radius:10px;background:var(--warning-soft);color:var(--warning);line-height:1.65}.historical-legend{display:flex;flex-wrap:wrap;gap:8px}.historical-legend span{display:inline-flex;align-items:center;min-height:30px;padding:4px 8px;border-radius:7px;font-size:12px;line-height:1.35}.historical-scroll{width:100%;max-width:100%;min-width:0;overflow:auto;border:1px solid var(--line);border-radius:10px;overscroll-behavior-inline:contain}.historical-table{width:max-content;min-width:100%;border-collapse:separate;border-spacing:0;background:var(--surface)}.historical-table th,.historical-table td{min-width:118px;padding:8px;border-right:1px solid var(--line);border-bottom:1px solid var(--line);text-align:center}.historical-table thead th{position:sticky;top:0;z-index:2;background:var(--page);font-size:13px}.historical-table thead th:first-child{left:0;z-index:3;min-width:120px}.historical-table tbody th{position:sticky;left:0;z-index:1;background:var(--page);font-size:12px;white-space:nowrap}.historical-table th small{display:block;margin-top:4px;color:var(--muted);font-size:10px;font-weight:500}.historical-cell{display:grid;place-items:center;min-height:50px;padding:6px 8px;border-radius:8px;font-size:11px;line-height:1.35}.state-historical_selectable{background:repeating-linear-gradient(135deg,#edf4ef,#edf4ef 6px,#e1ebe3 6px,#e1ebe3 12px);color:#52675b}.state-historical_reserved{background:var(--danger-soft);color:var(--danger)}.state-historical_activity_occupied{background:#fff1df;color:#7d4a13}.state-historical_unbookable,.state-historical_unknown{background:#edf0ed;color:#6e7974}.historical-footer{margin:0;line-height:1.6}@media(max-width:600px){.historical-grid{padding:16px}.historical-table th,.historical-table td{min-width:108px;padding:6px}.historical-table thead th:first-child{min-width:112px}.historical-cell{min-height:58px;padding:5px;font-size:10px}}
</style>
