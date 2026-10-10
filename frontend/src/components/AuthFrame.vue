<script setup>
import AppIcon from './AppIcon.vue';
defineProps({ registration:Boolean });
</script>
<template><div class="auth-layout"><aside class="auth-story"><p class="eyebrow">YUMAO · YOUR COURT, YOUR CONTROL</p><h2>把准备做好，<br />把热爱留在球场。</h2><p>一个清晰、安全的羽毛球预约工作台。<br />从管理好你的账户与凭据开始。</p><div class="court-art" aria-hidden="true"><div class="court-outline"><span /><i /></div><div class="court-shuttle"><AppIcon name="court" /></div></div><div class="auth-story-footer"><AppIcon name="shield" /><span>独立账户 · 安全凭据 · 清晰状态</span></div></aside><section class="auth-form-area"><div class="auth-form-content"><span class="section-icon"><AppIcon :name="registration ? 'ticket' : 'user'" /></span><slot /></div><p class="auth-footnote">预约计划、自动执行与支付尚未开放。</p></section></div></template>
