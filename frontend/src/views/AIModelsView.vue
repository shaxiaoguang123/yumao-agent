<script setup>
import PageHeader from '../components/PageHeader.vue';
import AIModelsPanel from '../components/settings/AIModelsPanel.vue';
</script>
<template><div class="ai-models-page"><PageHeader eyebrow="工作空间设置" title="AI模型" description="管理自然语言意向整理使用的模型、密钥和默认选择。" /><AIModelsPanel /></div></template>
<style scoped>.ai-models-page{display:grid;gap:22px;min-width:0}</style>
