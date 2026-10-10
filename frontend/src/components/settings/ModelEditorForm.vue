<script setup>
import { computed, reactive, watch } from 'vue';

const props = defineProps({ model:{type:Object,default:null}, busy:Boolean });
const emit = defineEmits(['submit','cancel']);
const form = reactive({ name:'',base_url:'',model:'',auth_mode:'bearer',api_key:'',delete_api_key:false });
const editing = computed(()=>Boolean(props.model));
watch(()=>props.model,model=>{
  form.name=model?.name||'';form.base_url=model?.base_url||'';form.model=model?.model||'';
  form.auth_mode=model?.auth_mode||'bearer';form.api_key='';form.delete_api_key=false;
},{immediate:true});
watch(()=>form.auth_mode,mode=>{if(mode==='none')form.api_key='';});
watch(()=>form.delete_api_key,deleting=>{if(deleting)form.api_key='';});
function submit(){
  const payload={name:form.name.trim(),base_url:form.base_url.trim(),model:form.model.trim(),auth_mode:form.auth_mode};
  if(form.api_key&&!form.delete_api_key)payload.api_key=form.api_key;
  if(editing.value){payload.base_version=props.model.version;if(form.delete_api_key)payload.delete_api_key=true;}
  emit('submit',payload);
}
</script>

<template>
 <form class="model-editor form-stack" aria-label="AI模型配置" :aria-busy="busy" @submit.prevent="submit">
  <h2>{{ editing ? '编辑AI模型' : '添加AI模型' }}</h2>
  <label class="field">显示名称<input v-model="form.name" name="name" required maxlength="80" autocomplete="off" /></label>
  <label class="field">兼容接口地址<input v-model="form.base_url" name="base_url" type="url" required autocomplete="url" placeholder="https://api.example.com/v1" /></label>
  <label class="field">模型名称<input v-model="form.model" name="model" required maxlength="160" autocomplete="off" /></label>
  <label class="field">认证方式<select v-model="form.auth_mode" name="auth_mode"><option value="bearer">Bearer API Key</option><option value="none">无认证</option></select></label>
  <label class="field">{{ editing ? '替换 API Key（留空保持现有密钥）' : 'API Key' }}
   <input v-model="form.api_key" name="api_key" type="password" :required="!editing&&form.auth_mode==='bearer'" :disabled="form.auth_mode==='none'||form.delete_api_key" autocomplete="new-password" />
   <small class="field-hint">密钥只在提交时发送，不会回显。保存后仅显示是否已配置。</small>
  </label>
  <label v-if="editing && model.has_api_key" class="model-key-delete"><input v-model="form.delete_api_key" type="checkbox" />删除已保存的 API Key</label>
  <div class="model-actions"><button class="primary-button" type="submit" :disabled="busy">{{ busy ? '正在保存…' : '保存模型' }}</button><button class="secondary-button" type="button" :disabled="busy" @click="emit('cancel')">取消</button></div>
 </form>
</template>

<style scoped>
.model-editor{margin-top:0}.model-editor h2{margin:0}.model-key-delete{display:flex;align-items:center;gap:10px;min-height:44px}.model-key-delete input{width:18px;height:18px;accent-color:var(--danger)}.model-actions{display:flex;flex-wrap:wrap;gap:10px}
</style>
