import { describe, expect, it, vi } from 'vitest';
import { createPlanningProposalApi } from './planningProposals.js';

const api=()=>{const client={request:vi.fn(async()=>({status:'ready'}))};return {client,api:createPlanningProposalApi(client)};};

describe('planning proposal API',()=>{
 it('sends only the message and the credential on the first turn',async()=>{
  const {client,api:proposals}=api();await proposals.generate({message:'后天 14-16',credentialId:'cred-1'});
  expect(client.request).toHaveBeenCalledWith('/api/planning/queue-proposals',{method:'POST',body:{message:'后天 14-16',credential_id:'cred-1'}});
 });
 it('keeps the server conversation id on later turns and can restore or close it',async()=>{
  const {client,api:proposals}=api();
  await proposals.generate({message:'后天',credentialId:'cred-1',conversationId:'conversation-identifier-123'});
  expect(client.request.mock.calls[0][1].body.conversation_id).toBe('conversation-identifier-123');
  await proposals.restore('cred-1');
  expect(client.request.mock.calls[1][0]).toBe('/api/planning/queue-conversations?credential_id=cred-1');
  await proposals.close('conversation-identifier-123','cred-1');
  expect(client.request.mock.calls[2]).toEqual(['/api/planning/queue-conversations/conversation-identifier-123/close?credential_id=cred-1',{method:'POST',body:{}}]);
 });
 it('sends answers together with the field each earlier question was about',async()=>{
  const {client,api:proposals}=api();
  await proposals.generate({message:'原话',credentialId:'cred-1',answers:['14-16','不用'],askedFields:['windows_2h','more_2h']});
  expect(client.request.mock.calls[0][1].body).toEqual({message:'原话',credential_id:'cred-1',answers:['14-16','不用'],asked_fields:['windows_2h','more_2h']});
 });
 it('keeps null entries so asked fields stay aligned with the answers',async()=>{
  const {client,api:proposals}=api();
  await proposals.generate({message:'原话',credentialId:'cred-1',answers:['好'],askedFields:[null]});
  expect(client.request.mock.calls[0][1].body.asked_fields).toEqual([null]);
 });
 it('carries the query category only when the page knows it',async()=>{
  const {client,api:proposals}=api();
  await proposals.generate({message:'原话',credentialId:'cred-1',scopeLabel:'羽毛球'});
  expect(client.request.mock.calls[0][1].body.scope_label).toBe('羽毛球');
  await proposals.generate({message:'原话',credentialId:'cred-1',scopeLabel:''});
  expect(client.request.mock.calls[1][1].body).not.toHaveProperty('scope_label');
 });
 it('never sends plan identifiers or the removed question history',async()=>{
  const {client,api:proposals}=api();await proposals.generate({message:'x',credentialId:'c',answers:['a'],askedFields:[null]});
  const body=client.request.mock.calls[0][1].body;
  for(const key of ['plan_id','base_version','follow_up_questions'])expect(body).not.toHaveProperty(key);
 });
 it('requires an authenticated client',()=>{expect(()=>createPlanningProposalApi({})).toThrow(TypeError);});
});
