<script setup>
import PlanSnapshotDetails from './PlanSnapshotDetails.vue';
defineProps({revisions:{type:Array,default:()=>[]},status:String,hasMore:Boolean});
const emit=defineEmits(['close','retry','more']);
</script>
<template>
 <section class="panel" aria-labelledby="plan-history-title"><div class="plan-section-heading"><h2 id="plan-history-title">版本历史</h2><button class="secondary-button" type="button" @click="emit('close')">关闭历史</button></div>
 <p class="muted">每次有效修改保存为新的不可变版本。历史内容只读。</p>
 <p v-if="status==='loading'" class="status-loading" role="status">正在读取历史版本…</p>
 <div v-else-if="status==='error'" role="alert"><p class="form-error">历史版本读取失败。</p><button class="secondary-button" type="button" @click="emit('retry')">重试读取历史</button></div>
 <details v-for="revision in revisions" :key="revision.revision_id" class="plan-revision"><summary>版本 {{ revision.revision_number }} · {{ revision.intent.target_date }} · {{ revision.intent.venue_preference }}{{ revision.deleted?' · 已删除':'' }}</summary><PlanSnapshotDetails :snapshot="revision" /></details>
 <button v-if="hasMore" class="secondary-button" type="button" :disabled="status==='loading'" @click="emit('more')">加载更早版本</button>
 </section>
</template>
<style scoped>
.plan-revision{border-top:1px solid var(--line);padding:8px 0}.plan-revision summary{padding:8px 0;min-height:var(--control-height);cursor:pointer;line-height:1.7;overflow-wrap:anywhere}
</style>
