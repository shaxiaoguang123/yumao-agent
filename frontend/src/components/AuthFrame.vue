<script setup>
import AppIcon from './AppIcon.vue';
defineProps({ registration: Boolean });
</script>
<template>
  <section class="auth-card">
    <div class="auth-card-mark" aria-hidden="true"><AppIcon name="court" /></div>
    <slot />
  </section>
</template>
