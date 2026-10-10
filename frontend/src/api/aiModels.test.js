import { describe, expect, it, vi } from 'vitest';
import { createAIModelsApi } from './aiModels.js';

describe('AI models API',()=>{
 it('uses the authenticated client and sends secret changes only in write bodies',async()=>{
  const client={request:vi.fn(async()=>({ok:true}))};const api=createAIModelsApi(client);
  await api.create({name:'Private',base_url:'https://provider.test/v1',model:'model-x',auth_mode:'bearer',api_key:'secret-value'});
  await api.update('model/a',{base_version:2,api_key:'replacement'});
  await api.update('model/a',{base_version:3,delete_api_key:true});
  await api.remove('model/a',4);await api.preferences('model/a','service_default');await api.test('model/a');
  expect(client.request.mock.calls).toEqual([
   ['/api/ai/models',{method:'POST',body:{name:'Private',base_url:'https://provider.test/v1',model:'model-x',auth_mode:'bearer',api_key:'secret-value'}}],
   ['/api/ai/models/model%2Fa',{method:'PATCH',body:{base_version:2,api_key:'replacement'}}],
   ['/api/ai/models/model%2Fa',{method:'PATCH',body:{base_version:3,delete_api_key:true}}],
   ['/api/ai/models/model%2Fa',{method:'DELETE',body:{base_version:4}}],
   ['/api/ai/models/preferences',{method:'PATCH',body:{selected_model_id:'model/a',default_model_id:'service_default'}}],
   ['/api/ai/models/model%2Fa/test',{method:'POST',body:{}}],
  ]);
 });
 it('requires an authenticated HTTP client',()=>expect(()=>createAIModelsApi({})).toThrow());
 it('turns a successful HTTP response with ok=false into a typed, safe failure',async()=>{
  const api=createAIModelsApi({request:vi.fn(async()=>({ok:false,error:'provider_timeout',status:504}))});
  await expect(api.test('model-1')).rejects.toMatchObject({code:'provider_timeout',status:504});
 });
});
