<script setup>
import AppIcon from '../AppIcon.vue';

const props = defineProps({
  mode: { type: String, default: 'new' },
  disabled: Boolean,
});
const emit = defineEmits(['update:mode']);

const choices = [
  { value: 'new', title: '新建预约意向', description: '从描述开始整理预约', icon: 'plus' },
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
.proposal-mode-picker{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px;margin-top:12px}
.proposal-mode-card{display:flex;align-items:center;gap:9px;min-width:0;min-height:54px;padding:8px 10px;text-align:left;border:1px solid var(--line);border-radius:10px;background:var(--surface);color:var(--ink);cursor:pointer;transition:background-color 120ms ease,border-color 120ms ease}
.proposal-mode-card:hover:not(:disabled){border-color:var(--brand);background:var(--brand-soft)}
.proposal-mode-card.is-selected{border-color:var(--brand);background:var(--brand-soft);box-shadow:inset 0 0 0 1px var(--brand)}
.proposal-mode-card:focus-visible{outline:3px solid var(--brand);outline-offset:2px}
.proposal-mode-card:disabled{opacity:.6;cursor:not-allowed}
.proposal-mode-card>.app-icon{flex:none;color:var(--brand-dark)}
.proposal-mode-card strong,.proposal-mode-card small{display:block}
.proposal-mode-card strong{font-size:12px;line-height:1.4}
.proposal-mode-card small{margin-top:2px;color:var(--muted);font-size:11px;line-height:1.35}
@media(max-width:560px){.proposal-mode-picker{grid-template-columns:minmax(0,1fr)}.proposal-mode-card strong{font-size:14px}.proposal-mode-card small{font-size:12px}}
@media(prefers-reduced-motion:reduce){.proposal-mode-card{transition:none}}
</style>
