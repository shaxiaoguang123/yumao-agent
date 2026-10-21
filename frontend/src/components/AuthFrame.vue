<script setup>
import AppIcon from './AppIcon.vue';
defineProps({ registration: Boolean });
</script>
<template>
  <section class="auth-card">
    <div class="auth-card-mark" aria-hidden="true"><AppIcon name="court" /></div>
    <slot />
    <p class="auth-footnote">自动预约与支付可按计划执行；请先配置凭据并启用执行器。</p>
  </section>
</template>
