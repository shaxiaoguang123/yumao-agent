import { flushPromises, mount, enableAutoUnmount } from '@vue/test-utils';
import { createMemoryHistory, createRouter, RouterView } from 'vue-router';
import { reactive } from 'vue';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { context, windowState } from '../components/plans/testFixtures.js';
import PlansView from './PlansView.vue';

enableAutoUnmount(afterEach);
const candidate=(court='6号场',start='18:00',duration=120,scope='羽毛球')=>({court_preferences:[court],preferred_start_times:[start],duration_minutes:duration,query_scope_label:scope});
const queue=(date,credentialId='credential-a',candidates=[candidate()])=>({plan_id:`queue-${date}`,target_date:date,credential_id:credentialId,version:3,candidates});
const bookingWindow={...windowState,business_date:'2026-10-15',default_target_date:'2026-10-17',target_date:'2026-10-17',queryable_target_dates:['2026-10-15','2026-10-16','2026-10-17']};
const credentials=[
 {credential_id:'credential-a',label:'Token A',enabled:true,has_payment_password:true,account_binding_state:'confirmed',requires_revalidation:false,last_confirmed_validation_state:'confirmed_valid',expiry_state:'expiry_ok'},
 {credential_id:'credential-b',label:'Token B',enabled:true,has_payment_password:true,account_binding_state:'confirmed',requires_revalidation:false,last_confirmed_validation_state:'confirmed_valid',expiry_state:'expiry_ok'},
];
function apiFixture(overrides={}){
 const queuesByCredential={'credential-a':[queue('2026-10-17'),queue('2026-10-20','credential-a',[candidate('2号场','19:00',60)])],'credential-b':[queue('2026-10-16','credential-b')]};
 return {
  list:vi.fn(async()=>({plans:[]})),options:vi.fn(async()=>({context})),window:vi.fn(async()=>bookingWindow),executionSuccesses:vi.fn(async()=>({successes:[],worker_enabled:false})),
  queues:vi.fn(async(id)=>({queues:queuesByCredential[id]||[]})),
  queue:vi.fn(async(date,id)=>({queue:(queuesByCredential[id]||[]).find(item=>item.target_date===date)||{target_date:date,credential_id:id,version:0,candidates:[]}})),
  saveQueue:vi.fn(async(date,version,entries,id)=>({queue:{...queue(date,id,entries.map(item=>candidate(item.court_preference,item.start_time,item.duration_minutes,item.scope_label))),version:version+1}})),
  removeQueue:vi.fn(async()=>({})),queueRevisions:vi.fn(async()=>({revisions:[]})),
  ...overrides,
 };
}
async function mountPlans(api=apiFixture(),extraProvide={},startPath='/plans'){
 const router=createRouter({history:createMemoryHistory(),routes:[{path:'/plans',name:'plans',component:PlansView},{path:'/ai-models',name:'ai-models',component:{template:'<div />'}},{path:'/credentials',name:'credentials',component:{template:'<div />'}},{path:'/login',name:'login',component:{template:'<div />'}}]});await router.push(startPath);await router.isReady();
 const session=reactive({status:'authenticated',user:{user_id:'owner',username:'Owner'},csrfToken:'csrf-a',invalidationEpoch:0});
 const executionSettings=()=>({version:0,settings:{reconciliation_time:'00:30',clock_calibration_lead_ms:1000,start_offset_ms:0,booking_node_delay_ms:0,booking_by_time_delay_ms:0,get_user_info_delay_ms:0,get_pay_price_delay_ms:0,create_booking_delay_ms:0,open_platform_pay_order_delay_ms:0,payment_verify_delay_ms:0,payment_verify_interval_ms:3000,candidate_interval_ms:0},worker_enabled:false});
 const credentialApi={list:vi.fn(async()=>({credentials})),executionSettings:vi.fn(async()=>executionSettings()),updateExecutionSettings:vi.fn(async(version,settings)=>({version:version+1,settings,worker_enabled:false}))};
 const liveApi={
  options:vi.fn(async()=>({enabled:true,min_read_interval_ms:0})),
  categories:vi.fn(async()=>({data_state:'live_observed_unverified',source:'official_read_only',options:[{reference:'scope-a',label:'羽毛球',physical_venue_verified:false}]})),
  grid:vi.fn(async({targetDate})=>({grid_version:'official-bookingByTime-live-observation-v1',data_state:'live_observed_unverified',simulation:false,target_date:targetDate,timezone_name:'Asia/Shanghai',query_scope:{display_name:'羽毛球',physical_venue_verified:false},can_select:false,can_select_intent:true,can_match:false,can_bind:false,can_book:false,can_pay:false,can_create_job:false,client_selection_window:'open',source:{data_state:'live_observed_unverified',trust_state:'display_only_unverified',price_state:'displayed_unit_unverified',captured_at_utc_ms:Date.now(),ui_stale_after_utc_ms:Date.now()+60000},courts:[{display_name:'6号场'},{display_name:'5号场'}],rows:[{time_label:'18:00',time_status_code:'0',intent_start_time:'18:00',intent_end_time:'19:00',cells:[{state:'observed_unknown',price_display:null,selectable:false,intent_selectable:false},{state:'observed_unknown',price_display:null,selectable:false,intent_selectable:false}]}],notice:'测试观察'})),
 };
 const aiModelsApi={list:vi.fn(async()=>({effective_model_id:'model-a',models:[{id:'model-a',auth_mode:'bearer',has_api_key:true}],service_default:null})),test:vi.fn(async()=>({ok:true})),...extraProvide.aiModelsApi};
 const wrapper=mount({components:{RouterView},template:'<RouterView />'},{global:{plugins:[router],provide:{planApi:api,sessionStore:session,credentialApi,liveAvailabilityApi:liveApi,aiModelsApi,...extraProvide}}});
 await new Promise(resolve=>setTimeout(resolve,20));await flushPromises();return{wrapper,api,session,router,liveApi,credentialApi};
}

describe('reservation plan workspace',()=>{
 it('keeps the existing work areas and adds read-only order queries',async()=>{
  const {wrapper}=await mountPlans();
  expect(wrapper.findAll('[role="tab"]').map(tab=>tab.text().replace(/\s+/g,''))).toEqual(['查询场地','选择预约','Agent预约','抢票计划2','查询订单']);
  expect(wrapper.get('#plan-panel-query').isVisible()).toBe(true);
  await wrapper.get('[data-testid="plan-tab-manual"]').trigger('click');await flushPromises();
  expect(wrapper.get('#plan-panel-manual [data-testid="browse-date-0"]').text()).toContain('周四');
  expect(wrapper.find('#plan-panel-manual form').exists()).toBe(false);
 });
 it('opens and restores the order tab without calling the Agent provider',async()=>{
  const orderApi={query:vi.fn(async()=>({orders:[],status_options:[],page:1,page_size:10,total:0,total_pages:0,has_next:false})),details:vi.fn()};
  const {wrapper,router}=await mountPlans(apiFixture(),{orderApi});
  await wrapper.get('[data-testid="plan-tab-orders"]').trigger('click');await flushPromises();
  expect(router.currentRoute.value.query.tab).toBe('orders');
  expect(wrapper.get('#plan-panel-orders').isVisible()).toBe(true);
  expect(orderApi.query).toHaveBeenLastCalledWith({credentialId:'credential-a',page:1,status:''});
  await wrapper.get('[data-testid="plan-tab-current"]').trigger('click');await flushPromises();
  expect(wrapper.get('#plan-panel-current').isVisible()).toBe(true);
  await router.replace('/plans?tab=orders');await flushPromises();
  expect(wrapper.get('#plan-panel-orders').isVisible()).toBe(true);
 });
 it('does not start an Agent check after a booking setup guard redirects away from orders',async()=>{
  const orderApi={query:vi.fn(async()=>({orders:[],status_options:[],page:1,page_size:10,total:0,total_pages:0,has_next:false})),details:vi.fn()};
  const aiModelsApi={list:vi.fn(async()=>({effective_model_id:null,models:[]})),test:vi.fn()};
  const {wrapper,router}=await mountPlans(apiFixture(),{orderApi,aiModelsApi},'/plans?tab=orders');
  router.beforeEach(to=>to.name==='plans'&&to.query.tab==='agent'?{name:'credentials'}:true);
  await wrapper.get('[data-testid="plan-tab-agent"]').trigger('click');await flushPromises();
  expect(router.currentRoute.value.name).toBe('credentials');
  expect(aiModelsApi.list).not.toHaveBeenCalled();
 });
 it('renders every 09:00–22:00 hourly row for the selected Token and saves by credential scope',async()=>{
  const {wrapper,api}=await mountPlans();await wrapper.get('[data-testid="plan-tab-manual"]').trigger('click');await flushPromises();
  expect(wrapper.text()).toContain('Token A');
  expect(wrapper.findAll('.manual-queue-grid tbody tr')).toHaveLength(13);
  expect(wrapper.get('.manual-queue-grid tbody tr:first-child th').text()).toBe('09–10');
  expect(wrapper.get('.manual-queue-grid tbody tr:last-child th').text()).toBe('21–22');
  await wrapper.get('[data-testid="queue-cell-1-0"]').trigger('click');
  await new Promise(resolve=>setTimeout(resolve,500));await flushPromises();
  expect(api.saveQueue).toHaveBeenCalledWith('2026-10-17',3,[{court_preference:'6号场',start_time:'18:00',end_time:'20:00',duration_minutes:120,scope_label:'羽毛球'},{court_preference:'6号场',start_time:'10:00',end_time:'12:00',duration_minutes:120,scope_label:'羽毛球'}],'credential-a');
 });
 it('shows one saved-queue date and routes edit into the shared selector for the same Token',async()=>{
  const {wrapper,api}=await mountPlans();await wrapper.get('[data-testid="plan-tab-current"]').trigger('click');await flushPromises();
  expect(wrapper.get('[aria-label="编辑2026-10-20队列"]').element.disabled).toBe(false);
  await wrapper.get('[aria-label="编辑2026-10-20队列"]').trigger('click');await flushPromises();
  expect(wrapper.get('[data-testid="plan-tab-manual"]').attributes('aria-selected')).toBe('true');
  expect(wrapper.get('[data-testid="browse-date-extra"]').text()).toContain('周二');
  expect(wrapper.get('[data-testid="browse-date-extra"]').text()).toContain('10/20');
  expect(api.queue).toHaveBeenCalledWith('2026-10-20','credential-a');
 });
 it('keeps token and date filters in separate controls without inline queue editors',async()=>{
  const {wrapper}=await mountPlans();await wrapper.get('[data-testid="plan-tab-current"]').trigger('click');await flushPromises();
  expect(wrapper.find('.ticket-filter-bar .ticket-filter-credential').exists()).toBe(true);
  expect(wrapper.find('.ticket-filter-bar .ticket-filter-date input[type="date"]').exists()).toBe(true);
  expect(wrapper.find('.ticket-filter-meta button[aria-label="重新读取抢票计划"]').exists()).toBe(true);
  expect(wrapper.find('.ticket-queue-plans form').exists()).toBe(false);
  expect(wrapper.find('#plan-panel-current [aria-labelledby="execution-settings-title"]').exists()).toBe(true);
  expect(wrapper.find('#plan-panel-current [aria-labelledby="execution-settings-title"] h2').text()).toBe('自动执行时间');
 });
 it('loads one user execution schedule and does not reload it when switching Token',async()=>{
  const {wrapper,credentialApi}=await mountPlans();await wrapper.get('[data-testid="plan-tab-current"]').trigger('click');await flushPromises();
  expect(credentialApi.executionSettings).toHaveBeenCalledOnce();
  const credentialDisclosure=wrapper.get('#plan-panel-current .credential-popover');credentialDisclosure.element.open=true;await credentialDisclosure.trigger('toggle');await flushPromises();
  await wrapper.get('#plan-panel-current [data-testid="selection-credential"]').setValue('credential-b');await flushPromises();
  expect(credentialApi.executionSettings).toHaveBeenCalledOnce();
 });

 it('opens manual selection on the confirmed date when the assistant hands over',async()=>{
  const escalation={kind:'stalled',field:'venue_preference',message:'这一项我连续几次都没能确认。',prefill:{target_date:'2026-10-20'}};
  const planningProposalApi={generate:vi.fn(async()=>({status:'needs_input',questions:[escalation.message],proposal:null,conversation:{phase:'escalated',asking:'venue_preference',reason:'missing',turns_used:3,turns_max:12,attempts:{},slots:[],notices:[],escalation}}))};
  const {wrapper}=await mountPlans(apiFixture(),{planningProposalApi});
  await wrapper.get('[data-testid="plan-tab-agent"]').trigger('click');await flushPromises();
  await wrapper.get('[data-testid="proposal-message"]').setValue('想订场');await wrapper.get('[data-testid="generate-proposal"]').trigger('click');await flushPromises();
  await wrapper.get('[data-testid="open-manual"]').trigger('click');await flushPromises();
  expect(wrapper.get('[data-testid="plan-tab-manual"]').attributes('aria-selected')).toBe('true');
  expect(wrapper.get('#plan-panel-manual').isVisible()).toBe(true);
  expect(wrapper.get('#plan-panel-manual').text()).toContain('20');
 });

 it('checks the active AI model before showing Agent and redirects on provider failure',async()=>{
  const aiModelsApi={list:vi.fn(async()=>({effective_model_id:'model-fail',models:[{id:'model-fail',auth_mode:'bearer',has_api_key:true}]})),test:vi.fn(async()=>{throw Object.assign(new Error('provider auth failed'),{code:'provider_auth_failed'});})};
  const {wrapper,router}=await mountPlans(apiFixture(),{aiModelsApi});
  await wrapper.get('[data-testid="plan-tab-agent"]').trigger('click');await flushPromises();
  expect(aiModelsApi.test).toHaveBeenCalledWith('model-fail');
  expect(router.currentRoute.value.name).toBe('ai-models');
  expect(router.currentRoute.value.query).toEqual({returnTo:'agent',reason:'provider_auth_failed'});
 });

 it('redirects to model settings when no model is configured',async()=>{
  const aiModelsApi={list:vi.fn(async()=>({effective_model_id:null,models:[],service_default:null})),test:vi.fn()};
  const {wrapper,router}=await mountPlans(apiFixture(),{aiModelsApi});
  await wrapper.get('[data-testid="plan-tab-agent"]').trigger('click');await flushPromises();
  expect(aiModelsApi.test).not.toHaveBeenCalled();
  expect(router.currentRoute.value.name).toBe('ai-models');
  expect(router.currentRoute.value.query).toEqual({returnTo:'agent',reason:'provider_not_configured'});
 });

 it('preserves a direct Agent deep link while the date window loads',async()=>{
  const {wrapper}=await mountPlans(apiFixture(),{},'/plans?tab=agent');
  await flushPromises();
  expect(wrapper.get('[data-testid="plan-tab-agent"]').attributes('aria-selected')).toBe('true');
 });

 it('keeps Agent reachable for a temporary rate limit and offers a retry',async()=>{
  const aiModelsApi={list:vi.fn(async()=>({effective_model_id:'model-limited',models:[{id:'model-limited',auth_mode:'bearer',has_api_key:true}]})),test:vi.fn(async()=>{throw Object.assign(new Error('rate limited'),{code:'provider_rate_limited'});})};
  const {wrapper,router}=await mountPlans(apiFixture(),{aiModelsApi});
  await wrapper.get('[data-testid="plan-tab-agent"]').trigger('click');await flushPromises();
  expect(router.currentRoute.value.name).toBe('plans');
  expect(wrapper.get('#plan-panel-agent [role="alert"]').text()).toContain('服务商请求过于频繁');
  expect(wrapper.get('#plan-panel-agent [role="alert"] button').text()).toBe('重新检查');
 });

 it('falls back to the manual tab without a date when the hand-off carries none',async()=>{
  const escalation={kind:'turn_limit',field:null,message:'这次整理的轮数已经用完。',prefill:{}};
  const planningProposalApi={generate:vi.fn(async()=>({status:'needs_input',questions:[escalation.message],proposal:null,conversation:{phase:'escalated',asking:null,reason:null,turns_used:12,turns_max:12,attempts:{},slots:[],notices:[],escalation}}))};
  const {wrapper}=await mountPlans(apiFixture(),{planningProposalApi});
  await wrapper.get('[data-testid="plan-tab-agent"]').trigger('click');await flushPromises();
  await wrapper.get('[data-testid="proposal-message"]').setValue('想订场');await wrapper.get('[data-testid="generate-proposal"]').trigger('click');await flushPromises();
  await wrapper.get('[data-testid="open-manual"]').trigger('click');await flushPromises();
  expect(wrapper.get('[data-testid="plan-tab-manual"]').attributes('aria-selected')).toBe('true');
 });

 it('refreshes the manual queue list after the assistant saves a queue',async()=>{
  const entries=[{court_preference:'1号场',start_time:'14:00',end_time:'16:00',duration_minutes:120}];
  const proposal={kind:'manual_queue_draft',target_date:'2026-10-17',target_label:'10月17日 周六',entries,entry_count:1,base_version:3,existing_count:0,replaces_existing:false,schedule:{state:'scheduled',text:'ok'},execution_note:'note',warnings:[],review:{state:'reviewed'},provider:null,can_book:false,can_pay:false,can_create_job:false,can_query_upstream:false};
  const planningProposalApi={generate:vi.fn(async()=>({status:'ready',questions:[],proposal,conversation:{phase:'ready',asking:null,heading:null,strip:[],slots:[],notices:[],escalation:null,turns_used:0,turns_max:20}}))};
  const api=apiFixture({saveQueue:vi.fn(async(date,version,list)=>({queue:{...queue(date),version:version+1,candidates:[]}}))});
  const {wrapper}=await mountPlans(api,{planningProposalApi});
  await wrapper.get('[data-testid="plan-tab-agent"]').trigger('click');await flushPromises();
  await wrapper.get('[data-testid="proposal-message"]').setValue('周六 14-16 1号场');await wrapper.get('[data-testid="generate-proposal"]').trigger('click');await flushPromises();
  const before=api.queues.mock.calls.length;
  await wrapper.get('[data-testid="confirm-save-proposal"]').trigger('click');await flushPromises();
  expect(api.saveQueue).toHaveBeenCalledWith('2026-10-17',3,entries,'credential-a');
  expect(api.queues.mock.calls.length).toBeGreaterThan(before);
 });
});
