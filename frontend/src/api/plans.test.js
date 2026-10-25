import { describe, expect, it } from 'vitest';
import { createHttpClient } from './http.js';
import { intent } from '../components/plans/testFixtures.js';
describe('plans API boundary',()=>{
 it('uses real authenticated HTTP/CSRF contract and encoded identifiers',async()=>{const module=await import('./plans.js').catch(()=>null);expect(module).not.toBeNull();const calls=[];const client=createHttpClient({getCsrfToken:()=> 'synthetic-csrf',fetchImpl:async(path,init)=>{calls.push({path,init});return {ok:true,status:200,json:async()=>({plans:[]})};}});const api=module.createPlanApi(client);await api.list();await api.create(intent);await api.update('a/b',2,intent);await api.revisions('a/b');await api.window('2026-10-20');await api.options();expect(calls.map(c=>c.path)).toEqual(['/api/plans?view=current','/api/plans','/api/plans/a%2Fb','/api/plans/a%2Fb/revisions?limit=20','/api/booking-window?target_date=2026-10-20','/api/plans/options']);expect(calls.every(c=>c.init.credentials==='include')).toBe(true);expect(calls[1].init.headers['X-CSRF-Token']).toBe('synthetic-csrf');expect(JSON.parse(calls[2].init.body)).toEqual({base_version:2,intent});});
 it('uses scoped paginated summaries with cancellation and exact revision details',async()=>{
  const {createPlanApi}=await import('./plans.js'),calls=[];const controller=new AbortController();
  const api=createPlanApi({request:async(path,options)=>{calls.push({path,options});}});
  await api.queueOverview('token/a',{category:'all',target_date:'',page:2,limit:20},{signal:controller.signal});
  await api.executionQueue('2026-10-27','token/a','revision/a');
  expect(calls[0]).toEqual({path:'/api/plans/queue-overview?category=all&page=2&limit=20&credential_id=token%2Fa',options:{signal:controller.signal}});
  expect(calls[1].path).toBe('/api/booking-execution/credentials/token%2Fa/queues/2026-10-27?revision_id=revision%2Fa');
 });
 it('preserves safe backend field errors for inline form feedback',async()=>{const client=createHttpClient({fetchImpl:async()=>({ok:false,status:400,json:async()=>({error:'invalid_plan',fields:{duration_minutes:'时长无效'}})})});await expect(client.request('/api/plans',{method:'POST',body:{}})).rejects.toMatchObject({code:'invalid_plan',fields:{duration_minutes:'时长无效'}});});
});
