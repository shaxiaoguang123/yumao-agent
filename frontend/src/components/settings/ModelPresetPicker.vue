<script setup>
import AppIcon from '../AppIcon.vue';
import { MODEL_PRESETS } from './modelPresets.js';
defineProps({disabled:Boolean});
const emit=defineEmits(['select']);
</script>
<template>
 <div class="model-presets"><span>快速添加</span><button v-for="preset in MODEL_PRESETS" :key="preset.id" type="button" :disabled="disabled" :data-testid="`preset-${preset.id}`" @click="emit('select',preset)">{{ preset.label }}</button><details class="model-quick-guide"><summary><AppIcon name="info" />配置说明</summary><div><ol><li>选择服务预设，在服务商控制台创建 API Key。</li><li>按账户与地域填写 HTTPS 地址和密钥；“获取模型列表”可读取可用模型，也可手动填写。</li><li>保存后设为当前模型，再用“测试连接”检查配置。</li></ol><div class="model-guide-links"><a v-for="preset in MODEL_PRESETS" :key="preset.id" :href="preset.docs" target="_blank" rel="noopener noreferrer">{{ preset.label }} 官方 API 文档</a></div></div></details></div>
</template>
<style scoped>
.model-presets{display:flex;align-items:center;gap:8px;flex-wrap:wrap;font-size:12px}.model-presets>span{color:var(--muted)}.model-presets>button{min-height:var(--control-height);border:1px solid var(--line);border-radius:8px;background:var(--page);color:var(--ink);padding:8px 16px;font:inherit;cursor:pointer}.model-presets>button:hover{border-color:var(--brand);background:var(--brand-soft)}.model-quick-guide{margin-left:auto;position:relative}.model-quick-guide summary{min-height:var(--control-height);display:flex;align-items:center;gap:8px;cursor:pointer;color:var(--muted)}.model-quick-guide>div{position:absolute;right:0;width:340px;max-width:calc(100vw - 40px);padding:16px;border:1px solid var(--line);border-radius:8px;background:var(--surface);z-index:5;box-shadow:0 6px 20px #0001}.model-quick-guide ol{margin:0;padding-left:16px;line-height:1.8}.model-guide-links{display:flex;gap:8px;flex-wrap:wrap;margin-top:8px}@media(max-width:600px){.model-presets{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));align-items:stretch}.model-presets>span,.model-quick-guide{grid-column:1/-1}.model-presets>button,.model-quick-guide summary{min-height:var(--control-height);width:100%}.model-quick-guide{margin-left:0}.model-quick-guide>div{position:fixed;left:16px;right:16px;bottom:max(16px,env(safe-area-inset-bottom));width:auto;max-width:none;max-height:65vh;overflow:auto}}
</style>
