<script setup>
import AppIcon from '../AppIcon.vue';

const props = defineProps({
  mode: { type: String, default: 'new' },
  disabled: Boolean,
});
const emit = defineEmits(['update:mode']);

const choices = [
  { value: 'queue', title: '整理抢票队列', description: '从描述生成可核对的候选队列', icon: 'plus' },
  { value: 'edit', title: '修改已有计划', description: '核对并调整指定计划', icon: 'edit' },
];
</script>

<template>
  <div class="proposal-mode-picker" role="group" aria-label="选择预约计划类型">
    <button
      v-for="choice in choices"
      :key="choice.value"
      class="proposal-mode-card"
      :class="{ 'is-selected': props.mode === choice.value }"
      :data-testid="`proposal-mode-${choice.value}`"
      type="button"
      :aria-pressed="props.mode === choice.value"
      :disabled="disabled"
      @click="emit('update:mode', choice.value)"
    >
      <AppIcon :name="choice.icon" />
      <span><strong>{{ choice.title }}</strong><small>{{ choice.description }}</small></span>
    </button>
  </div>
</template>

<style scoped>
.proposal-mode-picker { display:flex; gap:4px; width:fit-content; max-width:100%; padding:4px; border:1px solid var(--line); border-radius:980px; background:var(--page); }
.proposal-mode-card { display:flex; align-items:center; justify-content:center; gap:6px; min-height:44px; min-width:0; padding:8px 14px; border:1px solid transparent; border-radius:980px; color:var(--muted); background:transparent; font:inherit; cursor:pointer; }
.proposal-mode-card.is-selected { color:var(--ink); background:var(--surface); border-color:var(--line); box-shadow:0 1px 4px rgba(0,0,0,.03); }
.proposal-mode-card:hover:not(:disabled) { color:var(--brand); }
.proposal-mode-card strong { display:block; font-size:13px; font-weight:500; }
.proposal-mode-card small { display:none; }
.proposal-mode-card .app-icon { width:16px; height:16px; }
.proposal-mode-card:disabled { opacity:.5; cursor:not-allowed; }
@media(max-width:600px) { .proposal-mode-picker { margin:0; width:100%; border:0; border-bottom:1px solid var(--line); border-radius:20px 20px 0 0; padding:4px 8px; } .proposal-mode-card { flex:1; padding:6px; } }
</style>
