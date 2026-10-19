import { describe, expect, it, vi } from 'vitest';
import { createIntentPlanningProposalApi } from './intentPlanningProposals.js';

describe('intent planning proposal API',()=>{
 it('keeps the existing plan id and base version in the edit contract',async()=>{
  const client={request:vi.fn(async()=>({status:'ready'}))};
  const api=createIntentPlanningProposalApi(client);
  await api.generate('只把优先场地改成4号场','plan-7',3,['4号场'],[['你想改哪项？']],'credential-a');
  expect(client.request).toHaveBeenCalledWith('/api/planning/proposals',{method:'POST',body:{
   message:'只把优先场地改成4号场',plan_id:'plan-7',base_version:3,answers:['4号场'],
   follow_up_questions:[['你想改哪项？']],credential_id:'credential-a',
  }});
 });

 it('requires the authenticated request client',()=>{
  expect(()=>createIntentPlanningProposalApi({})).toThrow(TypeError);
 });
 it('sends the server conversation id and can close its date anchor',async()=>{
  const client={request:vi.fn(async()=>({status:'needs_input'}))};
  const api=createIntentPlanningProposalApi(client);
  await api.generate('后天','plan-7',3,['18:00'],[['哪天？']],'credential-a','intent-conversation-123456');
  expect(client.request.mock.calls[0][1].body.conversation_id).toBe('intent-conversation-123456');
  await api.close('intent-conversation-123456');
  expect(client.request.mock.calls[1]).toEqual(['/api/planning/conversations/intent-conversation-123456/close',{method:'POST',body:{}}]);
 });
});
