<script setup>
import { computed, watch } from 'vue';
import AppIcon from '../AppIcon.vue';
import BookingDateStrip from './BookingDateStrip.vue';
import TokenExpiryBadge from './TokenExpiryBadge.vue';
import { useLiveAvailability } from '../../composables/useLiveAvailability.js';
import LiveAvailabilityGrid from './LiveAvailabilityGrid.vue';
const props=defineProps({active:{type:Boolean,default:true},credentialId:{type:String,default:''},credentialRefreshKey:{type:Number,default:0},calendarState:{type:Object,default:null},refreshKey:{type:Number,default:0},selectionDisabled:Boolean,api:{type:Object,required:true},credentialApi:{type:Object,required:true},session:{type:Object,required:true},targetDate:{type:String,default:''},contextKey:{type:String,default:''}});
const emit=defineEmits(['date-change','court-labels','queue-scope','update:credentialId']);
const state=useLiveAvailability({api:props.api,credentialApi:props.credentialApi,session:()=>props.session,targetDate:()=>props.targetDate,contextKey:()=>props.contextKey,active:()=>props.active});
const {autoLoading,refreshAvailability,enabled,optionsLoading,optionsError,disabledMessage,credentials,credentialsError,eligibleCredentials,selectedCredentialId,selectedCategory,categoriesLoading,gridLoading,grid,gridExpired,error,message,initialize,refreshCredentials}=state;
watch(()=>props.credentialId,value=>{if(value!==selectedCredentialId.value)selectedCredentialId.value=value;});
watch(selectedCredentialId,value=>emit('update:credentialId',value));
watch(()=>props.credentialRefreshKey,()=>refreshCredentials());
watch(()=>props.refreshKey,()=>refreshAvailability());
const busy=computed(()=>autoLoading.value||categoriesLoading.value||gridLoading.value);
const selectedCredential=computed(()=>credentials.value.find(item=>item.credential_id===selectedCredentialId.value)||credentials.value[0]||null);
watch(grid,value=>{if(value)emit('court-labels',value.courts.map(court=>court.display_name));});
watch(selectedCategory,value=>emit('queue-scope',value?.label||''),{immediate:true});
watch(selectedCredentialId,()=>emit('court-labels',[]));
</script>
<template>
 <section class="live-availability-panel" data-testid="live-availability-panel" aria-label="查询场地" :aria-busy="optionsLoading||busy">
  <BookingDateStrip :state="calendarState" :model-value="targetDate" @update:model-value="emit('date-change',$event)" @refresh="refreshAvailability()">
   <template #actions>
    <TokenExpiryBadge :credential="selectedCredential" :timezone-name="calendarState?.business_timezone_name||'Asia/Shanghai'" />
    <button v-if="enabled" class="secondary-button query-refresh" data-testid="query-live-grid" type="button" :disabled="busy||!targetDate||!selectedCredentialId" @click="refreshAvailability()" :aria-label="busy?'读取中…':'刷新场地'" :title="busy?'读取中…':'刷新场地'"><AppIcon name="refresh" :class="{'is-loading':busy}" /></button>
    <details v-if="enabled" class="query-settings"><summary aria-label="查询设置" title="查询设置"><AppIcon name="settings" /></summary><div class="query-settings-content"><label class="field">预约凭据<select v-model="selectedCredentialId" data-testid="live-credential" :disabled="busy"><option value="">选择已验证的凭据</option><option v-for="credential in eligibleCredentials" :key="credential.credential_id" :value="credential.credential_id">{{ credential.label }}</option></select></label><button class="secondary-button" type="button" :disabled="busy" aria-label="刷新凭据" title="刷新凭据" @click="refreshCredentials"><AppIcon name="refresh" /></button></div></details>
   </template>
  </BookingDateStrip>
  <div class="query-content">
   <p v-if="optionsLoading" class="status-loading" role="status">正在读取查询配置…</p>
   <p v-if="optionsError" class="form-error" role="alert">{{ optionsError }} <button type="button" class="secondary-button" @click="initialize">重试配置</button></p>
   <p v-if="!optionsLoading&&!optionsError&&!enabled" class="query-disabled" role="status">{{ disabledMessage }}</p>
   <template v-if="enabled">
    <p v-if="!eligibleCredentials.length" class="muted">请先添加并验证预约凭据。</p>
    <p v-if="credentialsError" class="form-error" role="alert">{{ credentialsError }}</p>
    <span class="sr-only" data-testid="live-target-date">{{ targetDate }}</span>
    <p v-if="error" class="form-error" role="alert">{{ error }}</p>
    <LiveAvailabilityGrid v-if="grid" :grid="grid" :expired="gridExpired" :context-key="contextKey" :selection-disabled="selectionDisabled" query-only />
    <div v-if="!grid&&!error" :aria-busy="busy" class="live-empty"><AppIcon name="court" /><p>{{ busy?'正在读取当天场地…':'请选择日期或刷新场地' }}</p></div>
   </template>
  </div>
 </section>
</template>
<style scoped>
.live-availability-panel{min-width:0;background:var(--surface);border:1px solid var(--line);border-radius:20px}.query-content{padding:8px 16px;min-width:0}.query-disabled{margin:0;padding:16px;border-radius:8px;background:var(--warning-soft);color:var(--warning);line-height:1.6}.live-availability-panel :deep(.date-strip-options>button[data-testid^="browse-date-"][aria-pressed=true]){background:var(--brand-dark);border-color:var(--brand-dark)}.live-availability-panel :deep(.date-strip-options>button[data-testid^="browse-date-"]){flex-direction:row;gap:8px;padding:8px 16px;min-width:94px;border-radius:20px}.live-availability-panel :deep(.date-strip-options>button[data-testid^="browse-date-"] strong){font-weight:400}.query-content p{margin:0}.query-refresh,.query-settings>summary{width:40px;min-height:40px;display:grid;place-items:center;border:1px solid var(--line);border-radius:8px;background:var(--surface);color:var(--muted);cursor:pointer;flex-shrink:0;padding:0}.query-settings{position:relative}.query-settings>summary{list-style:none}.query-settings>summary::-webkit-details-marker{display:none}.query-settings-content{position:absolute;right:0;top:calc(100% + 6px);display:flex;gap:8px;align-items:end;width:280px;padding:16px;border:1px solid var(--line);border-radius:8px;background:var(--surface);z-index:8;box-shadow:0 6px 20px #0001}.query-settings-content .field{flex:1;min-width:0;margin:0}.query-settings-content select{min-height:40px;width:100%}.query-settings-content button{min-width:40px;min-height:40px;padding:8px}.live-empty{min-height:170px;display:flex;align-items:center;justify-content:center;gap:8px;color:var(--muted)}.live-source-help{font-size:12px;margin-top:8px;color:var(--muted)}.live-source-help summary{display:flex;gap:8px;align-items:center;cursor:pointer;min-height:32px}.live-source-help p{line-height:1.7}.is-loading{animation:query-spin 1.2s linear infinite}@keyframes query-spin{to{transform:rotate(360deg)}}@media(prefers-reduced-motion:reduce){.is-loading{animation:none}}@media(max-width:600px){.live-availability-panel :deep(.date-strip-options>button[data-testid^="browse-date-"]){min-width:65px;flex:1 1 65px;padding:8px}.live-availability-panel :deep(.more-date){order:1;min-width:155px;flex:0 1 155px;margin-left:0}.live-availability-panel :deep(.more-date>.app-icon){display:none}.live-availability-panel :deep(.token-expiry){order:1;margin-left:auto}.query-content{padding:8px}.query-refresh,.query-settings>summary{min-height:var(--control-height);width:44px}.query-settings-content{width:250px}}
@media(max-width:600px){.live-availability-panel :deep(.date-strip-options>button[data-testid^="browse-date-"]){flex-direction:column;gap:0;min-width:64px;flex:1 1 64px;padding:5px}.live-availability-panel :deep(.date-strip-options>button[data-testid^="browse-date-"] span){font-size:11px;line-height:1.4}.live-availability-panel :deep(.date-strip-options>button[data-testid^="browse-date-"] strong){font-size:13px}.live-availability-panel :deep(.more-date){min-width:0;flex:1 1 140px}.query-refresh,.query-settings>summary{border-radius:12px}}
</style>
