<script setup>
import { computed, inject, onBeforeUnmount, ref, shallowRef, watch } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import AppIcon from '../AppIcon.vue';
import ModelPresetPicker from './ModelPresetPicker.vue';
import ModelEditorForm from './ModelEditorForm.vue';
import { providerDiscoveryErrorMessage, providerErrorMessage } from '../../api/providerErrors.js';
import { rememberAgentModelReady } from '../../utils/agentReadiness.js';

const api=inject('aiModelsApi');
const session=inject('sessionStore');
const route=useRoute(),router=useRouter();
const preset=shallowRef(null);
function choosePreset(value){clearDiscovery();editing.value=null;preset.value=value;adding.value=true;}
const state=ref(null),editing=shallowRef(null),adding=shallowRef(false);
const loading=shallowRef(false),busy=shallowRef(false),discovering=shallowRef(false),error=shallowRef(''),notice=shallowRef(''),discoveryError=shallowRef(''),discoveredModels=shallowRef([]),testingId=shallowRef('');
const selected=shallowRef(''),defaultId=shallowRef('');
const userModels=computed(()=>state.value?.models||[]);
const agentSetupMessage=computed(()=>route.query.returnTo==='agent'
 ? `Agent 暂不可用：${providerErrorMessage(typeof route.query.reason==='string'?route.query.reason:'provider_not_configured')}`
 : '');
let alive=true,epoch=0,sequence=0,discoverySequence=0;
const authorized=()=>session?.status==='authenticated'&&Boolean(session.user?.user_id);
function valid(generation,id){return alive&&generation===epoch&&id===session?.user?.user_id&&authorized();}
const testErrorMessage=providerErrorMessage;
const parsingResult=shallowRef(null),testingKind=shallowRef('');
function clearDiscovery(){discoverySequence++;discovering.value=false;discoveredModels.value=[];discoveryError.value='';}
async function load(){
 if(!authorized())return;const generation=epoch,id=session.user.user_id,request=++sequence;loading.value=true;error.value='';
 try{const result=await api.list();if(valid(generation,id)&&request===sequence){state.value=result;const configuredIds=new Set([...(result.models||[]).map(model=>model.id),...(result.service_default?['service_default']:[])]);selected.value=configuredIds.has(result.selected_model_id)?result.selected_model_id:result.effective_model_id||'';defaultId.value=result.default_model_id||'';}}
 catch{if(valid(generation,id)&&request===sequence){state.value=null;error.value='AI模型配置读取失败，请重试。';}}
 finally{if(valid(generation,id)&&request===sequence)loading.value=false;}
}
async function saveModel(payload){if(busy.value||!authorized())return;const generation=epoch,id=session.user.user_id;busy.value=true;parsingResult.value=null;error.value='';notice.value='';
 try{if(editing.value)await api.update(editing.value.id,payload);else await api.create(payload);if(!valid(generation,id))return;notice.value='模型配置已保存。';editing.value=null;adding.value=false;await load();}
 catch{if(valid(generation,id))error.value='模型保存失败，请检查配置后重试。';}finally{if(valid(generation,id))busy.value=false;}}
async function discoverModels(config){
 if(busy.value||discovering.value||!authorized())return;
 const generation=epoch,id=session.user.user_id,request=++discoverySequence;
 discovering.value=true;discoveredModels.value=[];discoveryError.value='';error.value='';notice.value='';
 try{
  const result=config.saved_model_id?await api.discoverSaved(config.saved_model_id):await api.discover(config);
  if(!valid(generation,id)||request!==discoverySequence)return;
  if(!Array.isArray(result?.models))throw new Error('invalid_model_list');
  discoveredModels.value=result.models;
  notice.value=result.models.length?`读取到 ${result.models.length} 个模型，选择后会填入模型名称。`:'服务商返回了空模型列表，请检查 API Key 权限。';
 }catch(failure){if(valid(generation,id)&&request===discoverySequence)discoveryError.value=providerDiscoveryErrorMessage(failure);}
 finally{if(valid(generation,id)&&request===discoverySequence)discovering.value=false;}
}
async function removeModel(model){if(busy.value||!authorized())return;const generation=epoch,id=session.user.user_id;busy.value=true;parsingResult.value=null;error.value='';notice.value='';
 try{await api.remove(model.id,model.version);if(!valid(generation,id))return;notice.value='模型已删除。';await load();}
 catch{if(valid(generation,id))error.value='模型删除失败，可能已被其他窗口更新；请重新读取。';}finally{if(valid(generation,id))busy.value=false;}}
async function savePreferences(){if(busy.value||!authorized())return;const generation=epoch,id=session.user.user_id;busy.value=true;parsingResult.value=null;error.value='';notice.value='';
 try{await api.preferences(selected.value||null,defaultId.value||null);if(!valid(generation,id))return;notice.value='当前模型与默认模型已更新。';await load();}
 catch{if(valid(generation,id))error.value='偏好保存失败，请重新读取后重试。';}finally{if(valid(generation,id))busy.value=false;}}
async function testModel(model){if(!authorized()||busy.value||testingId.value)return;const generation=epoch,id=session.user.user_id;testingId.value=model.id;testingKind.value='connection';parsingResult.value=null;error.value='';notice.value='';
 try{const result=await api.test(model.id);if(valid(generation,id)){if(result?.ok===true){notice.value='模型连接成功。';if(model.id===state.value?.effective_model_id)rememberAgentModelReady(id,model.id);if(route.query.returnTo==='agent'&&model.id===state.value?.effective_model_id)await router.replace({name:'plans',query:{tab:'agent'}});}else error.value=testErrorMessage(result?.error);}}
 catch(failure){if(valid(generation,id))error.value=testErrorMessage(failure?.code);}finally{if(valid(generation,id))testingId.value='';}}
function returnToAgent(){return router.replace({name:'plans',query:{tab:'agent'}});}
async function testParsing(model){
 if(!authorized()||busy.value||testingId.value)return;
 const generation=epoch,id=session.user.user_id;testingId.value=model.id;testingKind.value='parsing';error.value='';notice.value='';parsingResult.value=null;
 try{const result=await api.testParsing(model.id);if(!valid(generation,id))return;
  parsingResult.value={...result,modelName:model.name};
  if(result.outcome==='parsed')notice.value='连接正常，追问优先级与队列复核测试通过。测试不会保存预约队列。';
  else if(result.outcome==='needs_input')notice.value='模型能够连接，但这条合成语句没有整理出完整队列。';
  else error.value='模型能够连接，但未能完成队列整理测试。';
 }catch(failure){if(valid(generation,id))error.value=testErrorMessage(failure?.code);}
 finally{if(valid(generation,id))testingId.value='';}
}
function editModel(model){clearDiscovery();preset.value=null;adding.value=false;editing.value={...model};}
function cancelEdit(){clearDiscovery();preset.value=null;editing.value=null;adding.value=false;}
watch(()=>[session?.status,session?.user?.user_id,session?.csrfToken],()=>{epoch++;sequence++;clearDiscovery();loading.value=false;busy.value=false;testingId.value='';testingKind.value='';parsingResult.value=null;state.value=null;editing.value=null;adding.value=false;preset.value=null;selected.value='';defaultId.value='';error.value='';notice.value='';if(authorized())void load();},{immediate:true,flush:'sync'});
onBeforeUnmount(()=>{alive=false;epoch++;sequence++;});
</script>

<template>
 <div class="ai-models-layout">
  <section class="panel ai-model-settings" aria-labelledby="ai-models-heading">
   <div class="section-heading"><h2 id="ai-models-heading">AI模型</h2><button class="secondary-button model-refresh" type="button" :disabled="loading" @click="load" aria-label="重新读取模型配置" title="重新读取"><AppIcon name="refresh" /></button></div>
   <p v-if="agentSetupMessage" class="model-feedback error agent-setup-message" role="alert">{{ agentSetupMessage }} <button class="text-button" type="button" :disabled="loading||Boolean(testingId)" @click="returnToAgent">我已完成调整，重新检查</button></p>
   <ModelPresetPicker :disabled="busy||Boolean(testingId)" @select="choosePreset" />
   <p v-if="error" class="model-feedback error" role="alert">{{ error }}</p><p v-if="notice" class="model-feedback success" role="status">{{ notice }}</p>
   <p v-if="loading && !state" class="muted" role="status">正在读取模型配置…</p>
   <template v-else-if="state">
    <p v-if="!userModels.length" class="model-empty">还没有配置可用模型 · 选择预设开始</p>
    <div v-if="userModels.length||state.service_default" class="preference-grid">
     <label class="field">当前使用模型<select v-model="selected" name="selected_model_id"><option value="">未选择</option><option v-if="state.service_default" value="service_default">服务默认 · {{ state.service_default.name }}</option><option v-for="model in userModels" :key="model.id" :value="model.id">{{ model.name }} · {{ model.model }}</option></select></label>
     <label class="field">默认模型<select v-model="defaultId" name="default_model_id"><option value="">未设置</option><option v-if="state.service_default" value="service_default">服务默认 · {{ state.service_default.name }}</option><option v-for="model in userModels" :key="model.id" :value="model.id">{{ model.name }} · {{ model.model }}</option></select></label>
    </div>
    <button v-if="userModels.length||state.service_default" class="primary-button preference-save" type="button" :disabled="busy" @click="savePreferences">保存模型选择</button>
    <div class="model-list" aria-label="已配置AI模型">
     <article v-for="model in userModels" :key="model.id" class="model-row">
      <div class="model-main"><div class="model-title"><h3>{{ model.name }}</h3><span v-if="selected===model.id" class="model-tag">当前使用</span><span v-if="defaultId===model.id" class="model-tag">默认</span></div><p>{{ model.model }} · {{ model.base_url }}</p><small>{{ model.has_api_key ? 'API Key 已配置（不会显示密钥）' : '尚未配置 API Key' }} · {{ model.auth_mode==='bearer'?'Bearer认证':'认证' }}</small></div>
      <div class="model-actions"><button class="secondary-button" type="button" :disabled="busy||Boolean(testingId)" @click="testModel(model)">{{ testingId===model.id&&testingKind==='connection'?'正在测试…':'测试连接' }}</button><button class="secondary-button" data-testid="test-model-parsing" type="button" :disabled="busy||Boolean(testingId)" @click="testParsing(model)">{{ testingId===model.id&&testingKind==='parsing'?'正在解析…':'测试计划解析能力' }}</button><button class="secondary-button" type="button" :disabled="busy||Boolean(testingId)" @click="editModel(model)">编辑</button><button class="danger-button" type="button" :disabled="busy||Boolean(testingId)" @click="removeModel(model)">删除</button></div>
     </article>
     <article v-if="state.service_default" class="model-row service-model"><div class="model-main"><div class="model-title"><h3>{{ state.service_default.name }}</h3><span class="model-tag">服务提供</span><span v-if="selected==='service_default'" class="model-tag">当前使用</span><span v-if="defaultId==='service_default'" class="model-tag">默认</span></div><p>{{ state.service_default.model }} · {{ state.service_default.base_url }}</p><small>由服务配置 · 不展示或修改密钥</small></div><div class="model-actions"><button class="secondary-button" type="button" :disabled="busy||Boolean(testingId)" @click="testModel(state.service_default)">{{ testingId==='service_default'&&testingKind==='connection'?'正在测试…':'测试连接' }}</button><button class="secondary-button" type="button" :disabled="busy||Boolean(testingId)" @click="testParsing(state.service_default)">测试计划解析能力</button></div></article>
    </div>
   </template>
   <section v-if="parsingResult" class="parsing-preview" aria-label="模型解析能力测试结果">
    <h3>{{ parsingResult.modelName }} · 队列整理测试</h3>
    <ol v-if="parsingResult.proposal?.entries?.length" class="parsing-entries"><li v-for="entry in parsingResult.proposal.entries" :key="`${entry.duration_minutes}-${entry.start_time}-${entry.court_preference}`">{{ entry.duration_minutes===120?'2小时':'1小时' }} {{ entry.start_time }}-{{ entry.end_time }} {{ entry.court_preference }}</li></ol>
    <ul v-if="parsingResult.questions?.length"><li v-for="(question,index) in parsingResult.questions" :key="index">{{ question }}</li></ul>
    <p class="muted">使用服务器合成语句，验证模型能选择下一项追问并按格式复核队列；不保存队列，也不代表可执行预约。</p>
   </section>
   <button v-if="!adding&&!editing" class="secondary-button add-model" type="button" :disabled="busy" @click="adding=true">添加AI模型</button>
   <ModelEditorForm v-if="adding||editing" :model="editing" :initial-preset="preset" :busy="busy||discovering" :discover-busy="discovering" :discovered-models="discoveredModels" :discovery-error="discoveryError" @submit="saveModel" @cancel="cancelEdit" @discover="discoverModels" @clear-discovery="clearDiscovery" />
  </section>
 </div>
</template>

<style scoped>
.parsing-preview{padding:16px;border:1px solid var(--line);border-radius:16px}.ai-model-settings{display:grid;gap:8px;padding:16px}.section-heading h2{font-size:20px}.model-refresh{margin-left:auto;min-width:36px;min-height:var(--control-height);display:grid;place-items:center;padding:8px}.model-empty{font-size:13px;margin:0!important;padding:8px 8px!important;border:0!important}.add-model{width:fit-content;min-height:var(--control-height);font-size:13px}.preference-save{min-height:var(--control-height);font-size:13px}.section-heading,.model-title,.model-actions{display:flex;align-items:center;gap:8px;flex-wrap:wrap}.section-heading{justify-content:space-between}.section-heading h2{margin:0}.model-empty{padding:16px;border:1px dashed var(--line);border-radius:16px;background:var(--page)}.model-empty p{margin:8px 0 0;color:var(--muted)}.preference-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px}.preference-save{justify-self:start}.model-list{display:grid}.model-row{display:flex;justify-content:space-between;align-items:center;gap:16px;padding:8px 0;border-top:1px solid var(--line)}.model-main{min-width:0}.model-main p{margin:8px 0;overflow-wrap:anywhere}.model-main small{color:var(--muted)}.model-title h3{margin:0}.model-tag{border-radius:999px;padding:8px 8px;background:var(--brand-soft);color:var(--brand-dark);font-size:12px}.service-model{opacity:.8}.model-feedback{padding:8px 16px;margin:0;border-radius:8px}.model-feedback.error{background:var(--danger-soft);color:var(--danger)}.model-feedback.success{background:var(--brand-soft);color:var(--brand-dark)}.agent-setup-message{display:flex;align-items:center;justify-content:space-between;gap:8px;flex-wrap:wrap}.agent-setup-message button{flex:0 0 auto}@media(max-width:720px){.preference-grid{grid-template-columns:1fr}.model-row{align-items:stretch;flex-direction:column}.model-actions{justify-content:flex-start}}
</style>
