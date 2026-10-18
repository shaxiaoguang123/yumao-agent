<script setup>
import { computed, onBeforeUnmount, ref } from 'vue';
const props=defineProps({credential:{type:Object,default:null},timezoneName:{type:String,default:'Asia/Shanghai'}});
const now=ref(Date.now());
const timer=setInterval(()=>{now.value=Date.now();},60000);
onBeforeUnmount(()=>clearInterval(timer));
const expires=computed(()=>typeof props.credential?.token_expires_at_utc==='string'?Date.parse(props.credential.token_expires_at_utc):NaN);
const remaining=computed(()=>expires.value-now.value);
const urgent=computed(()=>Number.isFinite(expires.value)&&remaining.value<=7*86400000);
const expired=computed(()=>Number.isFinite(expires.value)&&remaining.value<=0);
const dateLabel=computed(()=>Number.isFinite(expires.value)?new Intl.DateTimeFormat('zh-CN',{month:'2-digit',day:'2-digit',timeZone:props.timezoneName}).format(expires.value):'到期未知');
const detail=computed(()=>Number.isFinite(expires.value)?`Token 到期：${new Intl.DateTimeFormat('zh-CN',{dateStyle:'medium',timeStyle:'short',timeZone:props.timezoneName}).format(expires.value)}`:'凭据未提供可确认的 Token 到期时间');
</script>
<template>
 <span v-if="credential" class="token-expiry" :class="{'is-urgent':urgent,'is-pulsing':urgent&&!expired}" :title="detail" data-testid="token-expiry" role="status" aria-atomic="true">Token · {{ dateLabel }}<strong v-if="Number.isFinite(expires)"> · {{ expired?'已过期':`剩${Math.ceil(remaining/86400000)}天` }}</strong></span>
</template>
<style scoped>
.token-expiry{font-size:12px;color:var(--muted);white-space:nowrap;padding:8px 8px;border-radius:8px;background:var(--page)}.token-expiry strong{font-weight:600}.token-expiry.is-urgent{color:#b42318;background:#fff0ee}.token-expiry.is-pulsing{animation:token-expiry-pulse 1.8s ease-in-out infinite}@keyframes token-expiry-pulse{0%,100%{opacity:1}50%{opacity:.55}}@media(prefers-reduced-motion:reduce){.token-expiry.is-pulsing{animation:none}}
</style>
