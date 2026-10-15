import { flushPromises, mount, enableAutoUnmount } from '@vue/test-utils';
import { reactive } from 'vue';
import { afterEach, describe, expect, it, vi } from 'vitest';

enableAutoUnmount(afterEach);
const model={id:'model-1',name:'Work model',base_url:'https://provider.test/v1',model:'chat-model',auth_mode:'bearer',has_api_key:true,version:1,source:'user'};
function fixture(overrides={}){return {list:vi.fn(async()=>({models:[model],service_default:{...model,id:'service_default',name:'Service'},selected_model_id:'model-1',default_model_id:'service_default',effective_model_id:'model-1'})),create:vi.fn(async()=>({})),update:vi.fn(async()=>({})),remove:vi.fn(async()=>({})),preferences:vi.fn(async()=>({})),discover:vi.fn(async()=>({models:['deepseek-flash','qwen-plus']})),discoverSaved:vi.fn(async()=>({models:['chat-model','new-model']})),test:vi.fn(async()=>({ok:true,message:'连接成功'})),...overrides};}
async function mountPanel(api=fixture()) {const {default:component}=await import('./AIModelsPanel.vue');const session=reactive({status:'authenticated',user:{user_id:'owner'},csrfToken:'csrf-a'});const wrapper=mount(component,{global:{provide:{aiModelsApi:api,sessionStore:session}}});await flushPromises();return {wrapper,api,session};}

describe('AI models settings',()=>{
 it('shows an empty configuration as a setup prompt while preserving the service model option',async()=>{
  const {wrapper}=await mountPanel(fixture({list:vi.fn(async()=>({models:[],service_default:{...model,id:'service_default'},selected_model_id:null,default_model_id:null,effective_model_id:'service_default'}))}));
  expect(wrapper.text()).toContain('还没有配置可用模型');expect(wrapper.text()).toContain('服务提供');expect(wrapper.findAll('option').some(option=>option.text().includes('服务默认'))).toBe(true);
 });
 it('prefills verified provider presets without sending a model request and clears a typed key on provider change',async()=>{
  const {wrapper,api}=await mountPanel();await wrapper.get('[data-testid="preset-deepseek"]').trigger('click');
  expect(wrapper.get('[name="base_url"]').element.value).toBe('https://api.deepseek.com');expect(wrapper.get('[name="model"]').element.value).toBe('deepseek-flash');
  expect(api.create).not.toHaveBeenCalled();expect(api.test).not.toHaveBeenCalled();
  await wrapper.get('[name="api_key"]').setValue('private-pending-key');await wrapper.get('[name="model_preset"]').setValue('openai');
  expect(wrapper.get('[name="api_key"]').element.value).toBe('');expect(wrapper.get('[name="base_url"]').element.value).toBe('https://api.openai.com/v1');
  expect(wrapper.get('.model-quick-guide a').attributes('href')).toBe('https://api-docs.deepseek.com/api/list-models/');
 });
 it('reads available model IDs only on request and fills the editable model field',async()=>{
  const {wrapper,api}=await mountPanel();await wrapper.get('[data-testid="preset-deepseek"]').trigger('click');await wrapper.get('[name="api_key"]').setValue('ephemeral-discovery-key');
  await wrapper.get('[data-testid="discover-models"]').trigger('click');await flushPromises();
  expect(api.discover).toHaveBeenCalledWith({base_url:'https://api.deepseek.com',auth_mode:'bearer',api_key:'ephemeral-discovery-key'});
  expect(wrapper.findAll('[data-testid="discovered-model-select"] option').map(option=>option.element.value)).toEqual(['','deepseek-flash','qwen-plus']);
  await wrapper.get('[data-testid="discovered-model-select"]').setValue('qwen-plus');expect(wrapper.get('[name="model"]').element.value).toBe('qwen-plus');
  expect(wrapper.text()).not.toContain('ephemeral-discovery-key');expect(api.create).not.toHaveBeenCalled();
 });
 it('uses a saved model secret for a deliberate model-list request while editing',async()=>{
  const {wrapper,api}=await mountPanel();await wrapper.findAll('button').find(button=>button.text()==='编辑').trigger('click');
  await wrapper.get('[data-testid="discover-models"]').trigger('click');await flushPromises();
  expect(api.discoverSaved).toHaveBeenCalledWith('model-1');
  await wrapper.get('[data-testid="discovered-model-select"]').setValue('new-model');expect(wrapper.get('[name="model"]').element.value).toBe('new-model');
 });
 it('shows a local-service network reason when model discovery has no structured backend error',async()=>{
  const {wrapper}=await mountPanel(fixture({discoverSaved:vi.fn(async()=>{throw Object.assign(new Error('private stack detail'),{kind:'network'});})}));
  await wrapper.findAll('button').find(button=>button.text()==='编辑').trigger('click');
  await wrapper.get('[data-testid="discover-models"]').trigger('click');await flushPromises();
  expect(wrapper.get('.model-discovery-error').text()).toContain('浏览器无法连接预约工作台服务');
  expect(wrapper.text()).not.toContain('private stack detail');
 });
 it('maps provider discovery authorization failures to actionable safe guidance',async()=>{
  const {wrapper}=await mountPanel(fixture({discoverSaved:vi.fn(async()=>{throw Object.assign(new Error('private provider body'),{code:'provider_auth_failed'});})}));
  await wrapper.findAll('button').find(button=>button.text()==='编辑').trigger('click');
  await wrapper.get('[data-testid="discover-models"]').trigger('click');await flushPromises();
  expect(wrapper.get('.model-discovery-error').text()).toContain('认证失败');
  expect(wrapper.text()).not.toContain('private provider body');
 });
 it('creates a model and never displays a saved secret or echoes it into the edit form',async()=>{
  const {wrapper,api}=await mountPanel();
  await wrapper.get('.add-model').trigger('click');await wrapper.get('[name="name"]').setValue('New provider');await wrapper.get('[name="base_url"]').setValue('https://new.test/v1');await wrapper.get('[name="model"]').setValue('new-chat');await wrapper.get('[name="api_key"]').setValue('do-not-echo-this');await wrapper.get('form').trigger('submit');await flushPromises();
  expect(api.create).toHaveBeenCalledWith({name:'New provider',base_url:'https://new.test/v1',model:'new-chat',auth_mode:'bearer',api_key:'do-not-echo-this'});expect(wrapper.text()).not.toContain('do-not-echo-this');
  await wrapper.findAll('button').find(button=>button.text()==='编辑').trigger('click');expect(wrapper.get('[name="api_key"]').element.value).toBe('');expect(wrapper.text()).toContain('API Key 已配置（不会显示密钥）');
 });
 it('updates preferences, tests safely, and sends base version on deletion',async()=>{
  const {wrapper,api}=await mountPanel();await wrapper.get('[name="selected_model_id"]').setValue('service_default');await wrapper.get('[name="default_model_id"]').setValue('model-1');await wrapper.get('.preference-save').trigger('click');await flushPromises();expect(api.preferences).toHaveBeenCalledWith('service_default','model-1');
  await wrapper.findAll('button').find(button=>button.text()==='测试连接').trigger('click');await flushPromises();expect(wrapper.text()).toContain('模型连接成功');
  await wrapper.findAll('button').find(button=>button.text()==='删除').trigger('click');await flushPromises();expect(api.remove).toHaveBeenCalledWith('model-1',1);
 });
 it('shows a safe connection reason when the test endpoint returns ok=false with HTTP 200',async()=>{
  const {wrapper}=await mountPanel(fixture({test:vi.fn(async()=>({ok:false,error:'provider_timeout',status:504}))}));await wrapper.findAll('button').find(button=>button.text()==='测试连接').trigger('click');await flushPromises();expect(wrapper.text()).toContain('连接超时');expect(wrapper.text()).not.toContain('模型连接成功');
 });
 it.each([
  ['provider_auth_failed','认证失败或当前密钥没有访问权限'],
  ['access_denied','认证失败或当前密钥没有访问权限'],
  ['model_or_endpoint_not_found','模型或接口地址不存在'],
  ['rate_limited','服务商请求过于频繁'],
 ])('maps provider category %s to safe guidance',async(code,expected)=>{
  const {wrapper}=await mountPanel(fixture({test:vi.fn(async()=>({ok:false,error:code,status:400}))}));await wrapper.findAll('button').find(button=>button.text()==='测试连接').trigger('click');await flushPromises();expect(wrapper.text()).toContain(expected);
 });
 it('retains a blank secret on edit unless replacement or deletion was requested',async()=>{
  const {wrapper,api}=await mountPanel();await wrapper.findAll('button').find(button=>button.text()==='编辑').trigger('click');await wrapper.get('[name="name"]').setValue('Renamed');await wrapper.get('form').trigger('submit');await flushPromises();expect(api.update).toHaveBeenCalledWith('model-1',{name:'Renamed',base_url:model.base_url,model:model.model,auth_mode:'bearer',base_version:1});
 });
 it('sends an explicit secret replacement or deletion without exposing the stored value',async()=>{
  const {wrapper,api}=await mountPanel();await wrapper.findAll('button').find(button=>button.text()==='编辑').trigger('click');await wrapper.get('[name="api_key"]').setValue('replacement-secret');await wrapper.get('form').trigger('submit');await flushPromises();expect(api.update).toHaveBeenCalledWith('model-1',{name:model.name,base_url:model.base_url,model:model.model,auth_mode:'bearer',api_key:'replacement-secret',base_version:1});expect(wrapper.text()).not.toContain('replacement-secret');
  await wrapper.findAll('button').find(button=>button.text()==='编辑').trigger('click');await wrapper.get('.model-key-delete input').setValue(true);await wrapper.get('form').trigger('submit');await flushPromises();expect(api.update).toHaveBeenLastCalledWith('model-1',{name:model.name,base_url:model.base_url,model:model.model,auth_mode:'bearer',base_version:1,delete_api_key:true});
 });
 it('clears a typed replacement when deletion is selected so the request cannot contain both',async()=>{
  const {wrapper,api}=await mountPanel();await wrapper.findAll('button').find(button=>button.text()==='编辑').trigger('click');await wrapper.get('[name="api_key"]').setValue('replacement-secret');await wrapper.get('.model-key-delete input').setValue(true);expect(wrapper.get('[name="api_key"]').element.value).toBe('');expect(wrapper.get('[name="api_key"]').element.disabled).toBe(true);await wrapper.get('form').trigger('submit');await flushPromises();expect(api.update).toHaveBeenCalledWith('model-1',{name:model.name,base_url:model.base_url,model:model.model,auth_mode:'bearer',base_version:1,delete_api_key:true});
 });
 it('clears pending flags and fences old mutations when the account changes',async()=>{
  let resolveCreate;const api=fixture({create:vi.fn(()=>new Promise(resolve=>{resolveCreate=resolve;}))});const {wrapper,session}=await mountPanel(api);await wrapper.get('.add-model').trigger('click');await wrapper.get('[name="name"]').setValue('Pending');await wrapper.get('[name="base_url"]').setValue('https://pending.test/v1');await wrapper.get('[name="model"]').setValue('pending');await wrapper.get('[name="api_key"]').setValue('pending-key');await wrapper.get('form').trigger('submit');expect(wrapper.get('form').attributes('aria-busy')).toBe('true');
  session.user={user_id:'other'};await flushPromises();expect(wrapper.find('form').exists()).toBe(false);expect(wrapper.get('.preference-save').element.disabled).toBe(false);resolveCreate({});await flushPromises();expect(wrapper.text()).not.toContain('模型保存失败');
 });
 it('only calls parsing on explicit click and renders needs-input results',async()=>{
  const api=fixture({testParsing:vi.fn(async()=>({ok:false,outcome:'needs_input',questions:['请补充场馆'],proposal:null}))});const {wrapper}=await mountPanel(api);expect(api.testParsing).not.toHaveBeenCalled();await wrapper.get('[data-testid="test-model-parsing"]').trigger('click');await flushPromises();expect(api.testParsing).toHaveBeenCalledWith('model-1');expect(wrapper.text()).toContain('模型能够连接，但仍要求补充信息');expect(wrapper.text()).toContain('请补充场馆');
 });
 it.each([
  ['provider_access_denied','没有访问权限'],['provider_model_or_endpoint_not_found','模型或接口地址不存在'],['provider_rate_limited','服务商请求过于频繁'],['provider_response_invalid','不符合兼容接口要求'],['invalid_model_proposal','计划结构或字段依据不符合要求'],['ai_call_in_progress','已有模型调用正在进行'],['ai_call_rate_limited','模型调用过于频繁'],
 ])('uses actual backend category %s for parsing failure',async(code,text)=>{
  const api=fixture({testParsing:vi.fn(async()=>{throw {code,message:'raw secret supplier error'};})});const {wrapper}=await mountPanel(api);await wrapper.get('[data-testid="test-model-parsing"]').trigger('click');await flushPromises();expect(wrapper.text()).toContain(text);expect(wrapper.text()).not.toContain('raw secret');
 });

});
