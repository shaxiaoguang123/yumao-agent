<script setup>
import { computed, reactive, ref, watch } from 'vue';

import { MODEL_PRESETS } from './modelPresets.js';
const props = defineProps({ initialPreset:{type:Object,default:null}, model:{type:Object,default:null}, busy:Boolean, discoverBusy:Boolean, discoveredModels:{type:Array,default:()=>[]}, discoveryError:{type:String,default:''} });
const emit = defineEmits(['submit','cancel','discover','clear-discovery']);
const form = reactive({ name:'',base_url:'',model:'',auth_mode:'bearer',api_key:'',delete_api_key:false });
const presetId=ref('custom');
const selectedPreset=computed(()=>MODEL_PRESETS.find(p=>p.id===presetId.value));
function applyPreset(preset){if(editing.value)return;form.name=preset?.name||'';form.base_url=preset?.base_url||'';form.model=preset?.model||'';form.auth_mode='bearer';form.api_key='';form.delete_api_key=false;presetId.value=preset?.id||'custom';}
const editing = computed(()=>Boolean(props.model));
watch(()=>props.model,model=>{
  form.name=model?.name||'';form.base_url=model?.base_url||'';form.model=model?.model||'';
  form.auth_mode=model?.auth_mode||'bearer';form.api_key='';form.delete_api_key=false;
},{immediate:true});
watch(()=>props.initialPreset,preset=>{if(preset&&!editing.value)applyPreset(preset);},{immediate:true});
watch(()=>form.auth_mode,mode=>{if(mode==='none')form.api_key='';});
watch(()=>form.delete_api_key,deleting=>{if(deleting)form.api_key='';});
function submit(){
  const payload={name:form.name.trim(),base_url:form.base_url.trim(),model:form.model.trim(),auth_mode:form.auth_mode};
  if(form.api_key&&!form.delete_api_key)payload.api_key=form.api_key;
  if(editing.value){payload.base_version=props.model.version;if(form.delete_api_key)payload.delete_api_key=true;}
  emit('submit',payload);
}
const savedModelCanBeUsed=computed(()=>editing.value&&props.model?.has_api_key&&form.api_key===''&&form.base_url.trim()===props.model.base_url&&form.auth_mode===props.model.auth_mode);
const canDiscover=computed(()=>Boolean(form.base_url.trim())&&(form.auth_mode==='none'||Boolean(form.api_key)||savedModelCanBeUsed.value));
function discover(){
 if(!canDiscover.value||props.discoverBusy||props.busy)return;
 emit('discover',savedModelCanBeUsed.value?{saved_model_id:props.model.id}:{base_url:form.base_url.trim(),auth_mode:form.auth_mode,...(form.auth_mode==='bearer'?{api_key:form.api_key}:{})});
}
</script>

<template>
 <form class="model-editor form-stack" aria-label="AI模型配置" :aria-busy="busy" @submit.prevent="submit">
  <h2>{{ editing ? '编辑AI模型' : '添加AI模型' }}</h2>
  <label v-if="!editing" class="field preset-field">服务预设<select v-model="presetId" name="model_preset" :disabled="busy" @change="applyPreset(selectedPreset)"><option value="custom">自定义兼容接口</option><option v-for="preset in MODEL_PRESETS" :key="preset.id" :value="preset.id">{{ preset.label }}</option></select></label>
  <p v-if="selectedPreset&&!editing" class="preset-hint">{{ selectedPreset.hint }} <a :href="selectedPreset.console" target="_blank" rel="noopener noreferrer">获取 Key</a> · <a :href="selectedPreset.docs" target="_blank" rel="noopener noreferrer">官方文档</a></p>
  <label class="field">显示名称<input v-model="form.name" name="name" required maxlength="80" autocomplete="off" :disabled="busy" /></label>
  <label class="field">兼容接口地址<input v-model="form.base_url" name="base_url" type="url" required autocomplete="url" placeholder="https://api.example.com/v1" :disabled="busy" @input="emit('clear-discovery')" /></label>
  <label class="field model-name-field">模型名称<input v-model="form.model" name="model" required maxlength="160" autocomplete="off" :disabled="busy" />
   <span class="model-discovery-actions"><button class="secondary-button" data-testid="discover-models" type="button" :disabled="!canDiscover||busy||discoverBusy" @click="discover">{{ discoverBusy?'正在读取…':'获取模型列表' }}</button><small>读取一次此接口可用的模型；选择结果会填入名称。</small></span>
  </label>
  <div v-if="discoveredModels.length" class="discovered-model-picker"><label class="field">已读取的模型<select data-testid="discovered-model-select" :value="form.model" :disabled="busy" @change="form.model=$event.target.value"><option value="" disabled>选择模型名称</option><option v-for="modelId in discoveredModels" :key="modelId" :value="modelId">{{ modelId }}</option></select></label><span>{{ discoveredModels.length }} 个模型可选</span></div>
  <p v-if="discoveryError" class="model-discovery-error" role="alert">{{ discoveryError }}</p>
  <p v-else-if="discoverBusy" class="model-discovery-note" role="status">正在向配置的 HTTPS 服务读取模型名称；不会保存 API Key。</p>
  <label class="field">认证方式<select v-model="form.auth_mode" name="auth_mode" :disabled="busy" @change="emit('clear-discovery')"><option value="bearer">Bearer API Key</option><option value="none">无认证</option></select></label>
  <label class="field">{{ editing ? '替换 API Key（留空保持现有密钥）' : 'API Key' }}
   <input v-model="form.api_key" name="api_key" type="password" :required="!editing&&form.auth_mode==='bearer'" :disabled="busy||form.auth_mode==='none'||form.delete_api_key" autocomplete="new-password" @input="emit('clear-discovery')" />

  </label>
  <label v-if="editing && model.has_api_key" class="model-key-delete"><input v-model="form.delete_api_key" type="checkbox" />删除已保存的 API Key</label>
  <div class="model-actions"><button class="primary-button" type="submit" :disabled="busy">{{ busy ? '正在保存…' : '保存模型' }}</button><button class="secondary-button" type="button" :disabled="busy" @click="emit('cancel')">取消</button></div>
 </form>
</template>

<style scoped>
.model-editor{margin-top:0;display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:16px}.model-editor>h2,.model-editor>.preset-field,.model-editor>.preset-hint,.model-editor>.model-key-delete,.model-editor>.model-actions,.model-editor>.discovered-model-picker,.model-editor>.model-discovery-error,.model-editor>.model-discovery-note{grid-column:1/-1}.model-editor h2{font-size:16px}.preset-hint{font-size:12px;line-height:1.6;margin:0;color:var(--muted)}@media(max-width:600px){.model-editor{grid-template-columns:minmax(0,1fr)}}.model-editor h2{margin:0}.model-key-delete{display:flex;align-items:center;gap:8px;min-height:var(--control-height)}.model-key-delete input{width:18px;height:18px;accent-color:var(--danger)}.model-actions{display:flex;flex-wrap:wrap;gap:8px}.model-name-field{align-self:start}.model-discovery-actions{display:flex;align-items:center;gap:8px;flex-wrap:wrap}.model-discovery-actions .secondary-button{min-height:var(--control-height);font-size:12px}.model-discovery-actions small,.discovered-model-picker>span{color:var(--muted);font-size:12px}.discovered-model-picker{display:flex;align-items:end;gap:8px}.discovered-model-picker>.field{flex:1}.discovered-model-picker>span{padding-bottom:16px}.model-discovery-error,.model-discovery-note{margin:0;font-size:12px;line-height:1.5;color:var(--muted)}.model-discovery-error{color:var(--danger)}
</style>
