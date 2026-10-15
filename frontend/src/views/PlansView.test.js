import { flushPromises, mount, enableAutoUnmount } from '@vue/test-utils';
import { createMemoryHistory, createRouter, RouterView } from 'vue-router';
import { reactive } from 'vue';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { context, windowState } from '../components/plans/testFixtures.js';
import PlansView from './PlansView.vue';

enableAutoUnmount(afterEach);
const candidate=(court='6号场',start='18:00',duration=120)=>({court_preferences:[court],preferred_start_times:[start],duration_minutes:duration});
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
  saveQueue:vi.fn(async(date,version,entries,id)=>({queue:{...queue(date,id,entries.map(item=>candidate(item.court_preference,item.start_time,item.duration_minutes))),version:version+1}})),
  removeQueue:vi.fn(async()=>({})),queueRevisions:vi.fn(async()=>({revisions:[]})),
  ...overrides,
 };
}
async function mountPlans(api=apiFixture()){
 const router=createRouter({history:createMemoryHistory(),routes:[{path:'/plans',component:PlansView}]});await router.push('/plans');await router.isReady();
 const session=reactive({status:'authenticated',user:{user_id:'owner',username:'Owner'},csrfToken:'csrf-a',invalidationEpoch:0});
 const credentialApi={list:vi.fn(async()=>({credentials}))};
 const wrapper=mount({components:{RouterView},template:'<RouterView />'},{global:{plugins:[router],provide:{planApi:api,sessionStore:session,credentialApi}}});
 await flushPromises();return{wrapper,api,session,router};
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
  expect(api.saveQueue).toHaveBeenCalledWith('2026-10-17',3,[{court_preference:'6号场',start_time:'18:00',end_time:'20:00',duration_minutes:120},{court_preference:'6号场',start_time:'10:00',end_time:'12:00',duration_minutes:120}],'credential-a');
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
 });
});
