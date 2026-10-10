import { HttpError } from './http.js';

export function createAIModelsApi(client) {
  if (typeof client?.request !== 'function') throw new TypeError('an authenticated HTTP client is required');
  return {
    list: () => client.request('/api/ai/models'),
    create: (model) => client.request('/api/ai/models', { method:'POST', body:model }),
    update: (id, changes) => client.request(`/api/ai/models/${encodeURIComponent(id)}`, { method:'PATCH', body:changes }),
    remove: (id, base_version) => client.request(`/api/ai/models/${encodeURIComponent(id)}`, { method:'DELETE', body:{base_version} }),
    preferences: (selected_model_id, default_model_id) => client.request('/api/ai/models/preferences', { method:'PATCH', body:{selected_model_id,default_model_id} }),
    test: async (id) => {
      const result=await client.request(`/api/ai/models/${encodeURIComponent(id)}/test`, { method:'POST', body:{} });
      if(result?.ok!==true){
        const code=typeof result?.error==='string'?result.error:'provider_test_failed';
        const status=Number.isInteger(result?.status)?result.status:0;
        const kind=status===504?'timeout':code==='provider_unavailable'?'network':'http';
        throw new HttpError(code,{code,status,kind});
      }
      return result;
    },
  };
}
