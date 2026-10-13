<script setup>
import { computed } from 'vue';
import { useLiveAvailability } from '../../composables/useLiveAvailability.js';
import LiveAvailabilityGrid from './LiveAvailabilityGrid.vue';
const props = defineProps({ api: { type: Object, required: true }, credentialApi: { type: Object, required: true }, session: { type: Object, required: true }, targetDate: { type: String, default: '' }, contextKey: { type: String, default: '' } });
const state = useLiveAvailability({ api: props.api, credentialApi: props.credentialApi, session: () => props.session, targetDate: () => props.targetDate, contextKey: () => props.contextKey });
const { enabled, optionsLoading, optionsError, credentialsError, eligibleCredentials, selectedCredentialId, categories, selectedScopeReference, categoriesLoading, gridLoading, grid, gridExpired, error, message, initialize, refreshCredentials, loadCategories, queryGrid } = state;
const busy = computed(() => categoriesLoading.value || gridLoading.value);
</script>

<template>
  <section v-if="enabled || optionsLoading || optionsError" class="panel live-availability-panel" data-testid="live-availability-panel" aria-labelledby="live-availability-title">
    <header><p class="eyebrow">真实只读查询 · 本地显式启用</p><h2 id="live-availability-title">官方场地时间观察</h2></header>
    <p class="muted">沿用官方的类别选择与场地 × 时间布局。类别是查询范围，尚不能作为可信实体场馆绑定。读取由你手动触发，所有真实格子只读。</p>
    <p v-if="optionsLoading" role="status">正在读取查询配置…</p>
    <p v-if="optionsError" class="form-error" role="alert">{{ optionsError }} <button type="button" class="secondary-button" @click="initialize">重试配置</button></p>
    <template v-if="enabled">
      <div class="live-controls">
        <label class="field">预约凭据<select v-model="selectedCredentialId" data-testid="live-credential" :disabled="busy"><option value="">选择已验证的凭据</option><option v-for="credential in eligibleCredentials" :key="credential.credential_id" :value="credential.credential_id">{{ credential.label }}</option></select></label>
        <button class="secondary-button" type="button" :disabled="busy" @click="refreshCredentials">刷新凭据</button>
        <button class="secondary-button" data-testid="load-live-categories" type="button" :disabled="busy || !selectedCredentialId" @click="loadCategories">{{ categoriesLoading ? '读取类别中…' : '读取官方查询类别' }}</button>
      </div>
      <p v-if="!eligibleCredentials.length" class="muted">请先在预约凭据页面添加并验证自己的 Token。查询只使用所选凭据，不显示或返回 Token。</p>
      <p v-if="credentialsError" class="form-error" role="alert">{{ credentialsError }}</p>
      <div v-if="categories.length" class="live-controls">
        <label class="field">官方查询类别<select v-model="selectedScopeReference" data-testid="live-category" :disabled="busy"><option v-for="category in categories" :key="category.reference" :value="category.reference">{{ category.label }}</option></select></label>
        <div class="live-query-date"><span>当前计划目标日期</span><strong data-testid="live-target-date">{{ targetDate || '请先打开或新建计划' }}</strong></div>
        <button class="primary-button" data-testid="query-live-grid" type="button" :disabled="busy || !targetDate || !selectedScopeReference" @click="queryGrid">{{ gridLoading ? '正在读取…' : '读取官方时段（只读）' }}</button>
      </div>
      <p v-if="message" class="muted" role="status">{{ message }}</p>
      <p v-if="error" class="form-error" role="alert">{{ error }}</p>
      <LiveAvailabilityGrid v-if="grid" :grid="grid" :expired="gridExpired" />
    </template>
  </section>
</template>

<style scoped>
.live-availability-panel{display:grid;grid-template-columns:minmax(0,1fr);gap:16px;min-width:0;margin:22px 0}.live-availability-panel h2,.live-availability-panel p{margin:0}.live-controls{display:flex;flex-wrap:wrap;gap:12px;align-items:end;min-width:0}.live-controls .field{flex:1 1 220px;min-width:0}.live-controls select{width:100%;min-height:44px;min-width:0;max-width:100%}.live-query-date{display:grid;gap:8px;min-height:68px;align-content:center;font-size:14px}.live-query-date span{color:var(--muted)}@media(max-width:600px){.live-controls{align-items:stretch}.live-controls .field{flex-basis:100%}.live-controls button{width:100%;min-height:44px}.live-query-date{width:100%}}
</style>
