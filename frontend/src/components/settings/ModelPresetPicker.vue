<script setup>
import AppIcon from '../AppIcon.vue';
import { MODEL_PRESETS } from './modelPresets.js';
defineProps({disabled:Boolean});
const emit=defineEmits(['select']);
</script>
<template>
 <div class="model-presets"><span>快速添加</span><button v-for="preset in MODEL_PRESETS" :key="preset.id" type="button" :disabled="disabled" :data-testid="`preset-${preset.id}`" @click="emit('select',preset)">{{ preset.label }}</button><details class="model-quick-guide"><summary><AppIcon name="info" />配置教程</summary><div><ol><li>选择预设，在对应平台创建 API Key。</li><li>填写 Key，核对地址及模型名称，保存。</li><li>设为当前模型，点击“测试连接”和“测试计划解析能力”。</li></ol><div class="model-guide-links"><a v-for="preset in MODEL_PRESETS" :key="preset.id" :href="preset.docs" target="_blank" rel="noopener noreferrer">{{ preset.label }} 官方教程</a></div></div></details></div>
</template>
<style scoped>
.model-presets{display:flex;align-items:center;gap:7px;flex-wrap:wrap;font-size:12px}.model-presets>span{color:var(--muted)}.model-presets>button{min-height:36px;border:1px solid var(--line);border-radius:6px;background:var(--page);color:var(--ink);padding:6px 12px;font:inherit;cursor:pointer}.model-presets>button:hover{border-color:var(--brand);background:var(--brand-soft)}.model-quick-guide{margin-left:auto;position:relative}.model-quick-guide summary{min-height:36px;display:flex;align-items:center;gap:4px;cursor:pointer;color:var(--muted)}.model-quick-guide>div{position:absolute;right:0;width:340px;max-width:calc(100vw - 40px);padding:12px;border:1px solid var(--line);border-radius:8px;background:var(--surface);z-index:5;box-shadow:0 6px 20px #0001}.model-quick-guide ol{margin:0;padding-left:20px;line-height:1.8}.model-guide-links{display:flex;gap:8px;flex-wrap:wrap;margin-top:8px}@media(max-width:600px){.model-presets>button,.model-quick-guide summary{min-height:44px}}
</style>
