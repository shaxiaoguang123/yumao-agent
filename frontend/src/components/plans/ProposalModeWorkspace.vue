<script setup>
import { shallowRef } from 'vue';
import IntentPlanAssistant from './IntentPlanAssistant.vue';
import ProposalAssistant from './ProposalAssistant.vue';
import ProposalModePicker from './ProposalModePicker.vue';

defineProps({
  plans: { type: Array, default: () => [] },
  planApi: { type: Object, required: true },
  proposalApi: { type: Object, required: true },
  intentProposalApi: { type: Object, default: null },
  credentialApi: { type: Object, default: null },
  credentialRefreshKey: { type: Number, default: 0 },
  session: { type: Object, required: true },
  credentialId: { type: String, default: '' },
  scopeLabel: { type: String, default: '' },
});
const emit = defineEmits(['saved', 'refresh-request', 'manual-request', 'provider-unavailable']);
const mode = shallowRef('queue');
const started = shallowRef(false);
function setMode(value) {
  if (!started.value && (value === 'queue' || value === 'edit')) mode.value = value;
}
function markStarted() { started.value = true; }
function resetModeLock() { started.value = false; }
function onSaved(value) { started.value = false; emit('saved', value); }
</script>

<template>
  <section class="proposal-mode-workspace" aria-label="预约助手模式">
    <ProposalModePicker :mode="mode" :disabled="started" @update:mode="setMode" />
    <ProposalAssistant
      v-if="mode === 'queue'"
      :plan-api="planApi"
      :proposal-api="proposalApi"
      :credential-api="credentialApi"
      :credential-refresh-key="credentialRefreshKey"
      :session="session"
      :credential-id="credentialId"
      :scope-label="scopeLabel"
      @saved="onSaved"
      @mode-started="markStarted"
      @mode-reset="resetModeLock"
      @refresh-request="emit('refresh-request')"
      @manual-request="emit('manual-request', $event)"
      @provider-unavailable="emit('provider-unavailable', $event)"
    >
      <template #header-actions><slot name="header-actions" /></template>
    </ProposalAssistant>
    <IntentPlanAssistant
      v-else-if="intentProposalApi"
      :plans="plans"
      :plan-api="planApi"
      :proposal-api="intentProposalApi"
      :credential-api="credentialApi"
      :credential-refresh-key="credentialRefreshKey"
      :session="session"
      :credential-id="credentialId"
      @saved="onSaved"
      @mode-started="markStarted"
      @mode-reset="resetModeLock"
      @refresh-request="emit('refresh-request')"
      @provider-unavailable="emit('provider-unavailable', $event)"
    >
      <template #header-actions><slot name="header-actions" /></template>
    </IntentPlanAssistant>
    <p v-if="!intentProposalApi&&mode === 'edit'" class="mode-unavailable" role="status">修改已有计划服务当前不可用。</p>
  </section>
</template>

<style scoped>
.proposal-mode-workspace { display:grid; gap:12px; min-width:0; }
@media(max-width:600px) {
  .proposal-mode-workspace { gap:0; border:1px solid var(--line); border-radius:16px; background:var(--surface); }
  .proposal-mode-workspace :deep(.proposal-chat) { border:0; border-radius:0 0 16px 16px; }
}
.mode-unavailable { margin:0; padding:12px 16px; border-radius:12px; background:var(--warning-soft); color:var(--warning); }
</style>
