<script setup>
import { computed, inject, onBeforeUnmount, ref, shallowRef, watch } from 'vue';
import ModelEditorForm from './ModelEditorForm.vue';

const api=inject('aiModelsApi');
const session=inject('sessionStore');
const state=ref(null),editing=shallowRef(null),adding=shallowRef(false);
const loading=shallowRef(false),busy=shallowRef(false),error=shallowRef(''),notice=shallowRef(''),testingId=shallowRef('');
const selected=shallowRef(''),defaultId=shallowRef('');
const userModels=computed(()=>state.value?.models||[]);
let alive=true,epoch=0,sequence=0;
const authorized=()=>session?.status==='authenticated'&&Boolean(session.user?.user_id);
function valid(generation,id){return alive&&generation===epoch&&id===session?.user?.user_id&&authorized();}
function testErrorMessage(code){
 if(code==='provider_not_configured'||code==='provider_api_key_required')return '未配置可用认证密钥，请检查认证方式和 API Key。';
 if(code==='provider_timeout'||code==='provider_dns_timeout')return '连接超时，请检查服务地址和网络后重试。';
 if(code==='provider_address_rejected'||code==='provider_redirect_rejected')return '服务地址未通过安全校验，请使用可信的 HTTPS 接口地址。';
 if(code==='invalid_provider_config'||code==='provider_response_invalid')return '模型配置或服务商响应无效，请检查地址和模型名称。';
 if(code==='provider_auth_failed'||code==='access_denied')return '认证失败或当前密钥没有访问权限，请检查 API Key 和服务商授权。';
 if(code==='model_or_endpoint_not_found')return '模型或接口地址不存在，请检查模型名称和兼容接口地址。';
 if(code==='rate_limited')return '服务商请求过于频繁，请稍后再测试。';
 if(code==='provider_request_failed')return '服务商拒绝了连接请求，请核对 API Key、模型名称和请求权限。';
 if(code==='provider_unavailable')return '暂时无法连接服务商，请检查网络和服务状态。';
 return '模型连接失败，请检查地址、模型名称和密钥。';
}
async function load(){
 if(!authorized())return;const generation=epoch,id=session.user.user_id,request=++sequence;loading.value=true;error.value='';
 try{const result=await api.list();if(valid(generation,id)&&request===sequence){state.value=result;selected.value=result.selected_model_id||'';defaultId.value=result.default_model_id||'';}}
 catch{if(valid(generation,id)&&request===sequence){state.value=null;error.value='AI模型配置读取失败，请重试。';}}
 finally{if(valid(generation,id)&&request===sequence)loading.value=false;}
}
async function saveModel(payload){if(busy.value||!authorized())return;const generation=epoch,id=session.user.user_id;busy.value=true;error.value='';notice.value='';
 try{if(editing.value)await api.update(editing.value.id,payload);else await api.create(payload);if(!valid(generation,id))return;notice.value='模型配置已保存。';editing.value=null;adding.value=false;await load();}
 catch{if(valid(generation,id))error.value='模型保存失败，请检查配置后重试。';}finally{if(valid(generation,id))busy.value=false;}}
async function removeModel(model){if(busy.value||!authorized())return;const generation=epoch,id=session.user.user_id;busy.value=true;error.value='';notice.value='';
 try{await api.remove(model.id,model.version);if(!valid(generation,id))return;notice.value='模型已删除。';await load();}
 catch{if(valid(generation,id))error.value='模型删除失败，可能已被其他窗口更新；请重新读取。';}finally{if(valid(generation,id))busy.value=false;}}
async function savePreferences(){if(busy.value||!authorized())return;const generation=epoch,id=session.user.user_id;busy.value=true;error.value='';notice.value='';
 try{await api.preferences(selected.value||null,defaultId.value||null);if(!valid(generation,id))return;notice.value='当前模型与默认模型已更新。';await load();}
 catch{if(valid(generation,id))error.value='偏好保存失败，请重新读取后重试。';}finally{if(valid(generation,id))busy.value=false;}}
async function testModel(model){if(busy.value||testingId.value)return;const generation=epoch,id=session.user.user_id;testingId.value=model.id;error.value='';notice.value='';
 try{const result=await api.test(model.id);if(valid(generation,id)){if(result?.ok===true)notice.value='模型连接成功。';else error.value=testErrorMessage(result?.error);}}
 catch(failure){if(valid(generation,id))error.value=testErrorMessage(failure?.code);}finally{if(valid(generation,id))testingId.value='';}}
function editModel(model){adding.value=false;editing.value={...model};}
function cancelEdit(){editing.value=null;adding.value=false;}
watch(()=>[session?.status,session?.user?.user_id,session?.csrfToken],()=>{epoch++;sequence++;loading.value=false;busy.value=false;testingId.value='';state.value=null;editing.value=null;adding.value=false;selected.value='';defaultId.value='';error.value='';notice.value='';if(authorized())void load();},{immediate:true,flush:'sync'});
onBeforeUnmount(()=>{alive=false;epoch++;sequence++;});
</script>

<template>
 <div class="ai-models-layout">
  <section class="panel ai-model-settings" aria-labelledby="ai-models-heading">
   <div class="section-heading"><div><p class="eyebrow">设置 · AI模型</p><h2 id="ai-models-heading">模型与默认项</h2></div><button class="secondary-button" type="button" :disabled="loading" @click="load">重新读取</button></div>
   <p class="muted">API Key 以加密方式保存。设置当前使用模型和默认模型后，可在计划页使用自然语言整理意向。</p>
   <p v-if="error" class="model-feedback error" role="alert">{{ error }}</p><p v-if="notice" class="model-feedback success" role="status">{{ notice }}</p>
   <p v-if="loading && !state" class="muted" role="status">正在读取模型配置…</p>
   <template v-else-if="state">
    <div v-if="!userModels.length" class="model-empty"><strong>还没有配置可用模型</strong><p>添加一个兼容接口地址和模型名称，再保存密钥即可开始使用。</p></div>
    <div class="preference-grid">
     <label class="field">当前使用模型<select v-model="selected" name="selected_model_id"><option value="">未选择</option><option v-if="state.service_default" value="service_default">服务默认 · {{ state.service_default.name }}</option><option v-for="model in userModels" :key="model.id" :value="model.id">{{ model.name }} · {{ model.model }}</option></select></label>
     <label class="field">默认模型<select v-model="defaultId" name="default_model_id"><option value="">未设置</option><option v-if="state.service_default" value="service_default">服务默认 · {{ state.service_default.name }}</option><option v-for="model in userModels" :key="model.id" :value="model.id">{{ model.name }} · {{ model.model }}</option></select></label>
    </div>
    <button class="primary-button preference-save" type="button" :disabled="busy" @click="savePreferences">保存模型选择</button>
    <div class="model-list" aria-label="已配置AI模型">
     <article v-for="model in userModels" :key="model.id" class="model-row">
      <div class="model-main"><div class="model-title"><h3>{{ model.name }}</h3><span v-if="selected===model.id" class="model-tag">当前使用</span><span v-if="defaultId===model.id" class="model-tag">默认</span></div><p>{{ model.model }} · {{ model.base_url }}</p><small>{{ model.has_api_key ? 'API Key 已配置（不会显示密钥）' : '尚未配置 API Key' }} · {{ model.auth_mode==='bearer'?'Bearer认证':'认证' }}</small></div>
      <div class="model-actions"><button class="secondary-button" type="button" :disabled="busy||testingId===model.id" @click="testModel(model)">{{ testingId===model.id?'正在测试…':'测试连接' }}</button><button class="secondary-button" type="button" :disabled="busy||testingId===model.id" @click="editModel(model)">编辑</button><button class="danger-button" type="button" :disabled="busy||testingId===model.id" @click="removeModel(model)">删除</button></div>
     </article>
     <article v-if="state.service_default" class="model-row service-model"><div class="model-main"><div class="model-title"><h3>{{ state.service_default.name }}</h3><span class="model-tag">服务提供</span><span v-if="selected==='service_default'" class="model-tag">当前使用</span><span v-if="defaultId==='service_default'" class="model-tag">默认</span></div><p>{{ state.service_default.model }} · {{ state.service_default.base_url }}</p><small>由服务配置 · 不展示或修改密钥</small></div><div class="model-actions"><button class="secondary-button" type="button" :disabled="busy||testingId==='service_default'" @click="testModel(state.service_default)">{{ testingId==='service_default'?'正在测试…':'测试连接' }}</button></div></article>
    </div>
   </template>
   <button v-if="!adding&&!editing" class="secondary-button add-model" type="button" :disabled="busy" @click="adding=true">添加AI模型</button>
   <ModelEditorForm v-if="adding||editing" :model="editing" :busy="busy" @submit="saveModel" @cancel="cancelEdit" />
  </section>
 </div>
</template>

<style scoped>
.ai-model-settings{display:grid;gap:20px}.section-heading,.model-title,.model-actions{display:flex;align-items:center;gap:10px;flex-wrap:wrap}.section-heading{justify-content:space-between}.section-heading h2{margin:0}.model-empty{padding:18px;border:1px dashed var(--line);border-radius:12px;background:var(--page)}.model-empty p{margin:6px 0 0;color:var(--muted)}.preference-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:18px}.preference-save{justify-self:start}.model-list{display:grid}.model-row{display:flex;justify-content:space-between;align-items:center;gap:20px;padding:18px 0;border-top:1px solid var(--line)}.model-main{min-width:0}.model-main p{margin:6px 0;overflow-wrap:anywhere}.model-main small{color:var(--muted)}.model-title h3{margin:0}.model-tag{border-radius:999px;padding:3px 9px;background:var(--brand-soft);color:var(--brand-dark);font-size:12px}.service-model{opacity:.8}.model-feedback{padding:12px 14px;margin:0;border-radius:10px}.model-feedback.error{background:var(--danger-soft);color:var(--danger)}.model-feedback.success{background:var(--brand-soft);color:var(--brand-dark)}@media(max-width:720px){.preference-grid{grid-template-columns:1fr}.model-row{align-items:stretch;flex-direction:column}.model-actions{justify-content:flex-start}}
</style>
