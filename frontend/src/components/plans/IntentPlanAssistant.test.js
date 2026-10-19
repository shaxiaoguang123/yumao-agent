import { flushPromises, mount } from '@vue/test-utils';
import { reactive } from 'vue';
import { describe, expect, it, vi } from 'vitest';
import IntentPlanAssistant from './IntentPlanAssistant.vue';

const intent={target_date:'2026-10-24',preferred_start_times:['18:00'],duration_minutes:120,venue_preference:'东区体育馆',court_preferences:['6号场'],fallback_policy:{allow_any_court_in_venue:false,allow_time_shift:false,allowed_start_time_range:null},price_ceiling_minor:null};

describe('existing plan edit chat',()=>{
 it('loads the selected version and sends the plan id and version to the LLM proposal API',async()=>{
  const plan={plan_id:'plan-1',version:4,credential_id:null,intent,context:{timezone_name:'Asia/Shanghai',currency_code:null,currency_minor_unit_exponent:null}};
  const planApi={get:vi.fn(async()=>({plan})),update:vi.fn()};
  const proposalApi={generate:vi.fn(async()=>({status:'needs_input',questions:['你希望改成哪个场地？'],proposal:null}))};
  const session=reactive({status:'authenticated',user:{user_id:'owner'},csrfToken:'csrf'});
  const wrapper=mount(IntentPlanAssistant,{props:{plans:[plan],planApi,proposalApi,session,credentialId:''},global:{stubs:{RouterLink:{template:'<a><slot /></a>'}}}});
  await wrapper.get('#proposal-target-plan').setValue('plan-1');
  await wrapper.get('[data-testid="proposal-message"]').setValue('把优先场改成4号场');
  await wrapper.get('[data-testid="generate-proposal"]').trigger('click');
  await flushPromises();
  expect(planApi.get).toHaveBeenCalledWith('plan-1');
  expect(proposalApi.generate).toHaveBeenCalledWith('把优先场改成4号场','plan-1',4);
  expect(wrapper.text()).toContain('你希望改成哪个场地？');
  expect(planApi.update).not.toHaveBeenCalled();
 });

 it('saves the reviewed edit against the version it read',async()=>{
  const plan={plan_id:'plan-1',version:4,credential_id:null,intent,context:{timezone_name:'Asia/Shanghai',currency_code:null,currency_minor_unit_exponent:null}};
  const planApi={get:vi.fn(async()=>({plan})),update:vi.fn(async()=>({plan:{...plan,version:5,intent:{...intent,court_preferences:['4号场']}}}))};
  const updatedIntent={...intent,court_preferences:['4号场']};
  const proposal={status:'ready',questions:[],proposal:{kind:'unbound_draft',intent:updatedIntent,plan_id:'plan-1',base_version:4,before_intent:intent,
   changes:[{field:'court_preferences',before:['6号场'],after:['4号场']}],can_book:false,can_pay:false,can_create_job:false,can_query_upstream:false}};
  const proposalApi={generate:vi.fn(async()=>structuredClone(proposal))};
  const session=reactive({status:'authenticated',user:{user_id:'owner'},csrfToken:'csrf'});
  const wrapper=mount(IntentPlanAssistant,{props:{plans:[plan],planApi,proposalApi,session,credentialId:''},global:{stubs:{RouterLink:{template:'<a><slot /></a>'}}}});
  await wrapper.get('#proposal-target-plan').setValue('plan-1');
  await wrapper.get('[data-testid="proposal-message"]').setValue('把优先场地改成4号场');
  await wrapper.get('[data-testid="generate-proposal"]').trigger('click');
  await flushPromises();
  expect(wrapper.get('[data-testid="confirm-save-proposal"]').attributes('disabled')).toBeUndefined();
  await wrapper.get('[data-testid="confirm-save-proposal"]').trigger('click');
  await flushPromises();
  expect(planApi.update).toHaveBeenCalledWith('plan-1',4,updatedIntent);
  expect(wrapper.text()).toContain('预约意向已保存 · 版本 5');
 });
});
