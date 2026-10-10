<script setup>
defineProps({ eyebrow:String, title:String, description:String, titleId:String });
</script>
<template><header class="page-header"><div><p v-if="eyebrow" class="eyebrow">{{ eyebrow }}</p><h1 :id="titleId">{{ title }}</h1><p v-if="description" class="muted page-description">{{ description }}</p></div><div v-if="$slots.default" class="page-header-actions"><slot /></div></header></template>
