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
 {credential_id:'credential-a',label:'Token A',enabled:true,account_binding_state:'confirmed',requires_revalidation:false,last_confirmed_validation_state:'confirmed_valid',expiry_state:'expiry_ok'},
 {credential_id:'credential-b',label:'Token B',enabled:true,account_binding_state:'confirmed',requires_revalidation:false,last_confirmed_validation_state:'confirmed_valid',expiry_state:'expiry_ok'},
];
function apiFixture(overrides={}){
 const queuesByCredential={'credential-a':[queue('2026-10-17'),queue('2026-10-20','credential-a',[candidate('2号场','19:00',60)])],'credential-b':[queue('2026-10-16','credential-b')]};
 return {
  list:vi.fn(async()=>({plans:[]})),options:vi.fn(async()=>({context})),window:vi.fn(async()=>bookingWindow),
  queues:vi.fn(async(id)=>({queues:queuesByCredential[id]||[]})),
  queue:vi.fn(async(date,id)=>({queue:(queuesByCredential[id]||[]).find(item=>item.target_date===date)||{target_date:date,credential_id:id,version:0,candidates:[]}})),
  saveQueue:vi.fn(async(date,version,entries,id)=>({queue:{...queue(date,id,entries.map(item=>candidate(item.court_preference,item.start_time,item.duration_minutes,item.scope_label))),version:version+1}})),
  removeQueue:vi.fn(async()=>({})),queueRevisions:vi.fn(async()=>({revisions:[]})),
  ...overrides,
 };
}
async function mountPlans(api=apiFixture()){
 const router=createRouter({history:createMemoryHistory(),routes:[{path:'/plans',component:PlansView}]});await router.push('/plans');await router.isReady();
 const session=reactive({status:'authenticated',user:{user_id:'owner',username:'Owner'},csrfToken:'csrf-a',invalidationEpoch:0});
 const executionSettings=(credentialId)=>({credential_id:credentialId,version:0,settings:{reconciliation_time:'00:30',clock_calibration_lead_ms:1000,start_offset_ms:0,booking_node_delay_ms:0,booking_by_time_delay_ms:0,get_user_info_delay_ms:0,get_children_delay_ms:0,get_pay_price_delay_ms:0,create_booking_delay_ms:0,open_platform_pay_order_delay_ms:0,payment_verify_delay_ms:0},worker_enabled:false});
 const credentialApi={list:vi.fn(async()=>({credentials})),executionSettings:vi.fn(async id=>executionSettings(id)),updateExecutionSettings:vi.fn(async(id,version,settings)=>({credential_id:id,version:version+1,settings,worker_enabled:false}))};
 const liveApi={
  options:vi.fn(async()=>({enabled:true,min_read_interval_ms:0})),
  categories:vi.fn(async()=>({data_state:'live_observed_unverified',source:'official_read_only',options:[{reference:'scope-a',label:'羽毛球',physical_venue_verified:false}]})),
  grid:vi.fn(async({targetDate})=>({grid_version:'official-bookingByTime-live-observation-v1',data_state:'live_observed_unverified',simulation:false,target_date:targetDate,timezone_name:'Asia/Shanghai',query_scope:{display_name:'羽毛球',physical_venue_verified:false},can_select:false,can_select_intent:true,can_match:false,can_bind:false,can_book:false,can_pay:false,can_create_job:false,client_selection_window:'open',source:{data_state:'live_observed_unverified',trust_state:'display_only_unverified',price_state:'omitted_unit_unverified',captured_at_utc_ms:Date.now(),ui_stale_after_utc_ms:Date.now()+60000},courts:[{display_name:'6号场'},{display_name:'5号场'}],rows:[{time_label:'18:00',time_status_code:'0',intent_start_time:'18:00',intent_end_time:'19:00',cells:[{state:'observed_unknown',selectable:false,intent_selectable:false},{state:'observed_unknown',selectable:false,intent_selectable:false}]}],notice:'测试观察'})),
 };
 const wrapper=mount({components:{RouterView},template:'<RouterView />'},{global:{plugins:[router],provide:{planApi:api,sessionStore:session,credentialApi,liveAvailabilityApi:liveApi}}});
 await new Promise(resolve=>setTimeout(resolve,20));await flushPromises();return{wrapper,api,session,router,liveApi,credentialApi};
}

describe('reservation plan workspace',()=>{
 it('keeps the four work areas and uses the renamed ticket plan tab',async()=>{
  const {wrapper}=await mountPlans();
  expect(wrapper.findAll('[role="tab"]').map(tab=>tab.text().replace(/\s+/g,''))).toEqual(['查询场地','选择预约','Agent预约','抢票计划2']);
  expect(wrapper.get('#plan-panel-query').isVisible()).toBe(true);
  await wrapper.get('[data-testid="plan-tab-manual"]').trigger('click');await flushPromises();
  expect(wrapper.get('#plan-panel-manual [data-testid="browse-date-0"]').text()).toContain('周四');
  expect(wrapper.find('#plan-panel-manual form').exists()).toBe(false);
 });
 it('renders every 09:00–22:00 hourly row for the selected Token and saves by credential scope',async()=>{
  const {wrapper,api}=await mountPlans();await wrapper.get('[data-testid="plan-tab-manual"]').trigger('click');await flushPromises();
  expect(wrapper.text()).toContain('Token A');
  expect(wrapper.findAll('.manual-queue-grid tbody tr')).toHaveLength(13);
  expect(wrapper.get('.manual-queue-grid tbody tr:first-child th').text()).toBe('09:00–10:00');
  expect(wrapper.get('.manual-queue-grid tbody tr:last-child th').text()).toBe('21:00–22:00');
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
 it('loads the execution schedule for whichever Token is selected in the plan list',async()=>{
  const {wrapper,credentialApi}=await mountPlans();await wrapper.get('[data-testid="plan-tab-current"]').trigger('click');await flushPromises();
  expect(credentialApi.executionSettings).toHaveBeenCalledWith('credential-a');
  const credentialDisclosure=wrapper.get('#plan-panel-current .credential-popover');credentialDisclosure.element.open=true;await credentialDisclosure.trigger('toggle');await flushPromises();
  await wrapper.get('#plan-panel-current [data-testid="selection-credential"]').setValue('credential-b');await flushPromises();
  expect(credentialApi.executionSettings).toHaveBeenLastCalledWith('credential-b');
 });
});
