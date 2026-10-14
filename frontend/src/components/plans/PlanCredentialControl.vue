<script setup>
import { computed, onUnmounted, ref, watch } from 'vue';
import AppIcon from '../AppIcon.vue';
import TokenExpiryBadge from './TokenExpiryBadge.vue';
const props=defineProps({api:Object,session:Object,modelValue:{type:String,default:''},timezoneName:{type:String,default:'Asia/Shanghai'}});
const emit=defineEmits(['update:modelValue','updated']);
const credentials=ref([]),error=ref(''),token=ref(''),busy=ref(false),open=ref(false),success=ref('');
let generation=0,alive=true,sequence=0;
const selected=computed(()=>credentials.value.find(c=>c.credential_id===props.modelValue)||null);
const authenticated=()=>props.session?.status==='authenticated'&&Boolean(props.session.user?.user_id);
const valid=epoch=>alive&&epoch===generation&&authenticated();
async function load(){if(!props.api||!authenticated())return;const epoch=generation,seq=++sequence;try{const result=await props.api.list();if(!valid(epoch)||seq!==sequence)return;credentials.value=result.credentials;if(!credentials.value.some(c=>c.credential_id===props.modelValue))emit('update:modelValue',(credentials.value.find(c=>c.enabled&&c.last_confirmed_validation_state==='confirmed_valid'&&c.account_binding_state==='confirmed'&&!c.requires_revalidation&&c.expiry_state!=='expired')||credentials.value[0])?.credential_id||'');}catch{if(valid(epoch)&&seq===sequence)error.value='凭据读取失败。';}}
function clear(){token.value='';success.value='';error.value='';}
watch(()=>props.modelValue,clear,{flush:'sync'});
watch(open,value=>{if(!value)clear();});
watch(()=>[props.session?.status,props.session?.user?.user_id,props.session?.csrfToken,props.session?.invalidationEpoch],()=>{generation++;sequence++;credentials.value=[];clear();open.value=false;busy.value=false;if(authenticated())load();},{immediate:true,flush:'sync'});
async function rotate(){
 if(!selected.value||busy.value||!token.value)return;
 const epoch=generation,current=selected.value;busy.value=true;error.value='';success.value='';
 try{await props.api.rotateToken(current.credential_id,token.value,current.credential_version,current.current_token_revision_id);if(valid(epoch)){success.value='Token 已更换';await load();if(valid(epoch))emit('updated');}}
 catch(e){if(valid(epoch))error.value=({credential_account_mismatch:'新 Token 与当前账户不匹配，原凭据保持不变。',credential_version_conflict:'凭据已更新，请刷新后重试。',credential_token_expired:'新 Token 已过期。',credential_token_invalid:'新 Token 无效。',upstream_unavailable:'验证暂时失败，原凭据保持不变。'})[e?.code]||'更换未完成，请刷新凭据核对后重试。';}
 finally{if(valid(epoch)){token.value='';busy.value=false;}}
}
onUnmounted(()=>{alive=false;generation++;clear();});
</script>
<template>
 <div class="plan-credential-control"><TokenExpiryBadge :credential="selected" :timezone-name="timezoneName" />
  <details :open="open" class="credential-popover" @toggle="open=$event.target.open"><summary aria-label="查看或更换 Token" title="查看或更换 Token"><AppIcon name="key" /><span>Token</span></summary>
   <div v-if="open" class="credential-menu"><label class="field">预约凭据<select :value="modelValue" data-testid="selection-credential" :disabled="busy" @change="emit('update:modelValue',$event.target.value)"><option value="">选择凭据</option><option v-for="credential in credentials" :key="credential.credential_id" :value="credential.credential_id">{{ credential.label }}{{ credential.expiry_state==='expired'?'（已过期）':'' }}</option></select></label>
    <p v-if="selected" class="muted credential-detail">{{ selected.last_confirmed_validation_state==='confirmed_valid'&&!selected.requires_revalidation?'已验证':'待验证' }} · {{ selected.enabled?'已启用':'已停用' }}</p>
    <form v-if="selected" @submit.prevent="rotate"><label class="field">替换 Token<input v-model="token" data-testid="selection-token" type="password" autocomplete="off" :disabled="busy" placeholder="粘贴新 Token" /></label><button class="primary-button" type="submit" :disabled="busy||!token">{{ busy?'验证中…':'验证并更换' }}</button></form>
    <p v-if="error" class="form-error" role="alert">{{ error }}</p><p v-if="success" class="form-success" role="status">{{ success }}</p><div class="credential-menu-footer"><button type="button" class="text-button" :disabled="busy" @click="load">刷新凭据</button><RouterLink to="/credentials">管理凭据</RouterLink></div>
   </div>
  </details>
 </div>
</template>
<style scoped>
.plan-credential-control{display:flex;align-items:center;gap:6px;min-width:0}.credential-popover{position:relative}.credential-popover>summary{display:flex;align-items:center;gap:5px;min-height:40px;border:1px solid var(--line);border-radius:6px;padding:5px 10px;background:var(--surface);cursor:pointer;font-size:13px;list-style:none}.credential-popover>summary::-webkit-details-marker{display:none}.credential-menu{position:absolute;right:0;top:calc(100% + 8px);width:290px;max-width:calc(100vw - 40px);padding:14px;border:1px solid var(--line);border-radius:10px;background:var(--surface);box-shadow:0 8px 24px #0002;z-index:20}.credential-menu .field{font-size:13px;gap:5px}.credential-menu input,.credential-menu select{width:100%;min-height:40px;min-width:0}.credential-detail{font-size:12px;margin:8px 0}.credential-menu form{display:grid;gap:8px}.credential-menu-footer{display:flex;align-items:center;justify-content:space-between;font-size:13px;margin-top:10px}.credential-menu-footer button{padding:0;min-height:40px}.credential-menu p{font-size:12px}.credential-menu .primary-button{min-height:40px}
</style>
