<script setup>
import { computed } from 'vue';

const props=defineProps({catalog:{type:Object,required:true}});
const findingLabels={
  client_version_association:'尚未确认场馆数据与官方客户端版本的对应关系。',
  venue_list_response:'尚未取得可核验的官方场馆列表响应。',
  venue_name_to_parent_scope:'尚未确认场馆显示名到查询范围的对应关系。',
  physical_venue_label_to_parent_scope:'尚未确认用户可见的物理场馆名与查询范围；预约分类节点不能代替场馆。',
  court_to_venue_association:'尚未确认返回场地属于所选场馆。',
  booking_by_time_scope_response_association:'尚未确认时段响应属于哪个已选场馆。',
  booking_by_time_response_structure:'时段、冲突和价格字段结构尚未完整核实。',
  availability_status_semantics:'可用、占用和未知状态的含义尚未核实。',
  conflict_list_semantics:'冲突列表的字段和状态含义尚未核实。',
  time_atom_duration_continuity:'时段原子长度和连续组合规则尚未核实。',
  price_unit_currency_scope:'价格单位、币种和适用范围尚未核实。',
  capture_timestamp_freshness:'历史数据的采集时间和过期规则尚未核实。',
};
const blockers=computed(()=>[...new Set([
  ...(props.catalog.blocking_evidence||[]),
  ...(props.catalog.binding_blocking_evidence||[]),
  ...(props.catalog.availability_blocking_evidence||[]),
])].map(key=>findingLabels[key]).filter(Boolean));
const catalogConfigured=computed(()=>props.catalog.catalog_status==='configured');
const sourceStateLabel=computed(()=>props.catalog.source_state==='protocol_evidence_partial'?'协议证据部分确认':props.catalog.source_state==='reviewed_protocol_evidence'?'已关联经核验的协议证据':'尚无已核验来源');
</script>

<template>
  <section class="panel venue-catalog-status" data-testid="venue-catalog-status" aria-labelledby="venue-catalog-title">
    <div><p class="eyebrow">目录与数据来源</p><h2 id="venue-catalog-title">{{ catalogConfigured?`可信场馆目录 ${catalog.catalog_version}`:'可信场馆目录尚未配置' }}</h2></div>
    <p v-if="catalogConfigured">目录项来自已核验的版本。现有计划仍是未绑定草稿，本版本没有开放计划绑定。</p>
    <p v-else>计划里手工填写的物理场馆和场地仍是未核验偏好。预约分类节点不能据此绑定场馆，也不能确认真实可预约库存。</p>
    <p class="catalog-version">目录版本：{{ catalog.catalog_version||'未配置' }} · 来源状态：{{ sourceStateLabel }}</p>
    <details v-if="blockers.length">
      <summary>查看尚缺的协议证据</summary>
      <ul><li v-for="item in blockers" :key="item">{{ item }}</li></ul>
    </details>
  </section>
</template>

<style scoped>
.venue-catalog-status{display:grid;gap:10px;margin:0 0 22px}.venue-catalog-status h2,.venue-catalog-status p{margin:0}.venue-catalog-status .eyebrow{margin:0 0 6px}.venue-catalog-status details{line-height:1.7}.venue-catalog-status summary{cursor:pointer;font-weight:650}.venue-catalog-status ul{margin:8px 0 0;padding-left:22px}.catalog-version{color:var(--brand-dark);font-weight:600}
</style>
