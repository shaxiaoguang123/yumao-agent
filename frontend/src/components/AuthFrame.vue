<script setup>
import AppIcon from './AppIcon.vue';
defineProps({ registration: Boolean });
</script>
<template>
  <section class="auth-card">
    <div class="auth-card-mark" aria-hidden="true"><AppIcon name="court" /></div>
    <slot />
    <p class="auth-footnote">预约意向草稿已开放，自动预约与支付尚未开放。</p>
  </section>
</template>
