import { describe, expect, it, vi } from 'vitest';
import { createPlanningProposalApi } from './planningProposals.js';

describe('planning proposal API',()=>{
 it('sends the exact proposal contract',async()=>{
  const client={request:vi.fn(async()=>({status:'ready'}))};const api=createPlanningProposalApi(client);
  await api.generate('move to Saturday','plan/1',7);
  expect(client.request).toHaveBeenCalledWith('/api/planning/proposals',{method:'POST',body:{message:'move to Saturday',plan_id:'plan/1',base_version:7}});
 });
 it('keeps create requests explicitly unbound',async()=>{
  const client={request:vi.fn(async()=>({status:'needs_input'}))};const api=createPlanningProposalApi(client);
  await api.generate('weekend? ',null,null);
  expect(client.request.mock.calls[0][1].body).toEqual({message:'weekend? ',plan_id:null,base_version:null});
 });
 it('sends bounded user answers separately from untrusted prior questions',async()=>{
  const client={request:vi.fn(async()=>({status:'ready'}))};const api=createPlanningProposalApi(client);
  await api.generate('original',null,null,['venue'],[['Which venue?']]);
  expect(client.request.mock.calls[0][1].body).toEqual({message:'original',plan_id:null,base_version:null,answers:['venue'],follow_up_questions:[['Which venue?']]});
 });

});
