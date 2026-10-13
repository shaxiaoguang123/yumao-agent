<script setup>
import { computed } from 'vue';
import AppIcon from '../AppIcon.vue';
import { useLiveAvailability } from '../../composables/useLiveAvailability.js';
import LiveAvailabilityGrid from './LiveAvailabilityGrid.vue';
const props = defineProps({ api: { type: Object, required: true }, credentialApi: { type: Object, required: true }, session: { type: Object, required: true }, targetDate: { type: String, default: '' }, contextKey: { type: String, default: '' } });
const state = useLiveAvailability({ api: props.api, credentialApi: props.credentialApi, session: () => props.session, targetDate: () => props.targetDate, contextKey: () => props.contextKey });
const { enabled, optionsLoading, optionsError, credentialsError, eligibleCredentials, selectedCredentialId, categories, selectedScopeReference, categoriesLoading, gridLoading, grid, gridExpired, error, message, initialize, refreshCredentials, loadCategories, queryGrid } = state;
const busy = computed(() => categoriesLoading.value || gridLoading.value);
</script>

<template>
  <section v-if="enabled || optionsLoading || optionsError" class="panel live-availability-panel" data-testid="live-availability-panel" aria-labelledby="live-availability-title">
    <header class="live-panel-heading"><h2 id="live-availability-title">场地时段</h2><span class="live-readonly-tag">官方 · 只读</span></header>
    <p v-if="optionsLoading" role="status">正在读取查询配置…</p>
    <p v-if="optionsError" class="form-error" role="alert">{{ optionsError }} <button type="button" class="secondary-button" @click="initialize">重试配置</button></p>
    <template v-if="enabled">
      <div class="live-controls">
        <details class="query-settings"><summary aria-label="查询设置" title="查询设置"><AppIcon name="settings" /></summary><div class="query-settings-content"><label class="field">预约凭据<select v-model="selectedCredentialId" data-testid="live-credential" :disabled="busy"><option value="">选择已验证的凭据</option><option v-for="credential in eligibleCredentials" :key="credential.credential_id" :value="credential.credential_id">{{ credential.label }}</option></select></label><button class="secondary-button icon-control" type="button" :disabled="busy" aria-label="刷新凭据" title="刷新凭据" @click="refreshCredentials"><AppIcon name="refresh" /></button></div></details>
        <label v-if="categories.length" class="field live-category-field"><span class="sr-only">官方查询类别</span><select v-model="selectedScopeReference" aria-label="官方查询类别" data-testid="live-category" :disabled="busy"><option v-for="category in categories" :key="category.reference" :value="category.reference">{{ category.label }}</option></select></label>
        <button class="secondary-button" data-testid="load-live-categories" type="button" :aria-label="categories.length?'刷新类别':'加载类别'" :title="categories.length?'刷新类别':'加载类别'" :disabled="busy || !selectedCredentialId" @click="loadCategories"><AppIcon name="refresh" /><span v-if="!categories.length">{{ categoriesLoading ? '读取中…' : '加载类别' }}</span></button>
        <button v-if="categories.length" class="primary-button" data-testid="query-live-grid" type="button" :disabled="busy || !targetDate || !selectedScopeReference" @click="queryGrid"><AppIcon name="search" />{{ gridLoading ? '读取中…' : '查看时段' }}</button>
      </div>
      <p v-if="!eligibleCredentials.length" class="muted">请先添加并验证预约凭据。</p>
      <p v-if="credentialsError" class="form-error" role="alert">{{ credentialsError }}</p>
      <span class="sr-only" data-testid="live-target-date">{{ targetDate }}</span>

      <p v-if="error" class="form-error" role="alert">{{ error }}</p>
      <LiveAvailabilityGrid v-if="grid" :grid="grid" :expired="gridExpired" />
      <div v-if="!grid && !gridLoading && !error" class="live-empty"><AppIcon name="court" /><p>{{ categories.length ? '选择类别，查看当天时段' : '加载类别后查看场地时段' }}</p><span>只读查看 · 暂不支持真实选格</span></div>
      <details class="live-source-help"><summary aria-label="只读查询与场馆绑定有什么区别？"><AppIcon name="info" />查询说明</summary><p v-if="message" class="muted">{{ message }}</p><p class="muted">沿用官方的类别选择与场地 × 时间布局。类别是查询范围，尚不能作为可信实体场馆绑定。读取由你手动触发，所有真实格子只读。</p></details>
    </template>
  </section>
</template>

<style scoped>
.live-availability-panel{display:grid;grid-template-columns:minmax(0,1fr);gap:12px;min-width:0;margin:0}.live-panel-heading{display:flex;align-items:center;justify-content:space-between;gap:10px}.live-availability-panel h2{font-size:17px;margin:0}.live-availability-panel p{margin:0}.live-readonly-tag{font-size:12px;color:var(--muted)}.live-controls{display:flex;flex-wrap:wrap;gap:8px;align-items:center;min-width:0}.live-controls .field{min-width:0;margin:0}.live-category-field{flex:1 1 150px}.live-controls select{width:100%;min-height:44px;min-width:0;max-width:100%}.live-controls button{display:inline-flex;justify-content:center;align-items:center;gap:6px;min-height:44px;font-size:14px;white-space:nowrap;padding:10px 12px}.query-settings{display:contents}.query-settings>summary{display:grid;place-items:center;list-style:none;cursor:pointer;min-width:44px;min-height:44px;border:1px solid var(--line);border-radius:8px;color:var(--muted);order:4}.query-settings>summary::-webkit-details-marker{display:none}.query-settings[open]>summary{color:var(--brand);background:var(--brand-soft)}.query-settings-content{display:flex;align-items:end;gap:8px;flex-basis:100%;order:5;padding:12px;background:var(--page);border-radius:8px}.query-settings-content .field{flex:1}.icon-control{min-width:44px}.live-empty{display:flex;flex-direction:column;align-items:center;justify-content:center;gap:10px;min-height:170px;background:var(--page);border:1px dashed var(--line);border-radius:8px;color:var(--muted)}.live-empty>.app-icon{width:32px;height:32px}.live-empty p{font-size:14px}.live-empty span{font-size:12px}.live-source-help summary{display:flex;align-items:center;gap:5px;color:var(--muted);font-size:12px;cursor:pointer;min-height:30px;width:fit-content}.live-source-help summary .app-icon{width:16px;height:16px}.live-source-help p{margin-top:8px;line-height:1.6;font-size:13px}@media(max-width:600px){.live-category-field{flex:1 1 110px}.live-controls button{padding:10px}.live-controls .app-icon{width:17px;height:17px}.live-empty{min-height:160px}}
</style>
