import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils';
import { reactive } from 'vue';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import LiveAvailabilityPanel from './LiveAvailabilityPanel.vue';
enableAutoUnmount(afterEach);
beforeEach(()=>vi.useFakeTimers());afterEach(()=>vi.useRealTimers());
const credential=id=>({credential_id:id,label:`测试凭据 ${id}`,enabled:true,account_binding_state:'confirmed',requires_revalidation:false,last_confirmed_validation_state:'confirmed_valid',expiry_state:'valid'});
const categories={data_state:'live_observed_unverified',source:'official_read_only',options:[{reference:'other-ref',label:'游泳',physical_venue_verified:false},{reference:'badminton-ref',label:'羽毛球',physical_venue_verified:false}]};
function grid(date='2026-10-15'){
 return {grid_version:'official-bookingByTime-live-observation-v1',data_state:'live_observed_unverified',simulation:false,target_date:date,timezone_name:'Asia/Shanghai',query_scope:{display_name:'羽毛球',physical_venue_verified:false},can_select:false,can_select_intent:true,can_match:false,can_bind:false,can_book:false,can_pay:false,can_create_job:false,client_selection_window:'open',source:{data_state:'live_observed_unverified',trust_state:'display_only_unverified',price_state:'omitted_unit_unverified',captured_at_utc_ms:Date.now(),ui_stale_after_utc_ms:Date.now()+60000},courts:[{display_name:'测试一号场'}],rows:[{time_label:'18:00',time_status_code:'0',intent_start_time:'18:00',intent_end_time:'19:00',cells:[{state:'observed_unknown',selectable:false,intent_selectable:false}]}],notice:'未核验库存'};
}
const settle=async(ms=25)=>{await flushPromises();await vi.advanceTimersByTimeAsync(ms);await flushPromises();};
async function setup(overrides={},credentialOverrides={}){
 const api={options:vi.fn(async()=>({enabled:true,min_read_interval_ms:10})),categories:vi.fn(async()=>categories),grid:vi.fn(async({targetDate})=>grid(targetDate)),...overrides};
 const credentialApi={list:vi.fn(async()=>({credentials:[credential('a'),credential('b')]})),...credentialOverrides};
 const session=reactive({status:'authenticated',user:{user_id:'user-a'},csrfToken:'csrf-a'});
 const wrapper=mount(LiveAvailabilityPanel,{props:{api,credentialApi,session,targetDate:'2026-10-15',contextKey:'plan-v1'}});
 await settle();return {api,credentialApi,session,wrapper};
}
describe('badminton date-driven observation flow',()=>{
 it('automatically resolves badminton, omits the category box and disables unknown cells',async()=>{
  const {wrapper,api}=await setup();expect(api.categories).toHaveBeenCalledWith('a');
  expect(api.grid).toHaveBeenCalledWith({credentialId:'a',scopeReference:'badminton-ref',targetDate:'2026-10-15'});
  expect(wrapper.find('[data-testid="live-category"]').exists()).toBe(false);expect(wrapper.get('[data-testid="live-cell-0-0"]').element.disabled).toBe(true);expect(wrapper.text()).toContain('价格单位尚未核验');
 });
 it('keeps settings named and collapsed without another read',async()=>{
  const {wrapper,api}=await setup();const count=api.grid.mock.calls.length;expect(wrapper.get('.query-settings').attributes('open')).toBeUndefined();expect(wrapper.get('.query-settings>summary').attributes('aria-label')).toBe('查询设置');await wrapper.get('.query-settings').trigger('toggle');await settle();expect(api.grid).toHaveBeenCalledTimes(count);
 });
 it('refreshes on date change and coalesces rapid date changes to the last date',async()=>{
  const {wrapper,api}=await setup();await wrapper.setProps({targetDate:'2026-10-14'});await wrapper.setProps({targetDate:'2026-10-13'});expect(wrapper.find('[data-testid="live-availability-grid"]').exists()).toBe(false);await settle();expect(api.grid).toHaveBeenCalledTimes(2);expect(api.grid.mock.calls.at(-1)[0].targetDate).toBe('2026-10-13');
 });
 it('re-reads an already selected date through the explicit refresh signal',async()=>{
  const {wrapper,api}=await setup();await wrapper.setProps({refreshKey:1});await settle();
  expect(api.grid).toHaveBeenCalledTimes(2);expect(api.grid.mock.calls.at(-1)[0].targetDate).toBe('2026-10-15');
 });
 it('discards late data and serializes the newer date read',async()=>{
  let finish;const read=vi.fn().mockImplementationOnce(()=>new Promise(resolve=>{finish=resolve;})).mockImplementation(async({targetDate})=>grid(targetDate));const {wrapper}=await setup({grid:read});await wrapper.setProps({targetDate:'2026-10-14'});finish(grid());await flushPromises();expect(wrapper.find('[data-testid="live-availability-grid"]').exists()).toBe(false);await settle();expect(wrapper.get('[data-testid="live-availability-grid"]').text()).toContain('2026-10-14');
 });
 it('renews category references when credentials change',async()=>{
  const {wrapper,api}=await setup();await wrapper.get('[data-testid="live-credential"]').setValue('b');await settle();expect(api.categories.mock.calls.at(-1)[0]).toBe('b');expect(api.grid.mock.calls.at(-1)[0].credentialId).toBe('b');
 });
 it('cancels pending reads and removes observations on Session invalidation',async()=>{
  let finish;const {wrapper,session,api}=await setup({grid:vi.fn(()=>new Promise(resolve=>{finish=resolve;}))});session.status='unauthenticated';session.user=null;await settle();finish(grid());await settle();expect(wrapper.find('[data-testid="live-availability-grid"]').exists()).toBe(false);expect(api.grid).toHaveBeenCalledTimes(1);
 });
 it('shows window errors without retry loops or stale data',async()=>{
  const {wrapper,api}=await setup();api.grid.mockRejectedValueOnce({code:'booking_window_closed'});await wrapper.setProps({targetDate:'2026-10-20'});await settle();await settle(5000);expect(wrapper.text()).toContain('不在服务端允许的查询窗口');expect(api.grid).toHaveBeenCalledTimes(2);expect(wrapper.find('[data-testid="live-availability-grid"]').exists()).toBe(false);
 });
 it('waits for a server Retry-After at most once and uses the latest date',async()=>{
  const read=vi.fn().mockRejectedValueOnce({code:'upstream_rate_limited',retryAfterSeconds:2}).mockImplementation(async({targetDate})=>grid(targetDate));
  const {wrapper}=await setup({grid:read});await wrapper.setProps({targetDate:'2026-10-14'});
  await settle(1500);expect(read).toHaveBeenCalledTimes(1);
  await settle(600);expect(read).toHaveBeenCalledTimes(2);expect(read.mock.calls.at(-1)[0].targetDate).toBe('2026-10-14');
 });
 it('renews an expired scope at most once rather than asking for another date click',async()=>{
  const read=vi.fn().mockRejectedValueOnce({code:'live_query_scope_expired'}).mockImplementation(async({targetDate})=>grid(targetDate));
  const {api,wrapper}=await setup({grid:read});await settle();
  expect(api.categories).toHaveBeenCalledTimes(2);expect(read).toHaveBeenCalledTimes(2);
  expect(wrapper.find('[data-testid="live-availability-grid"]').exists()).toBe(true);
 });
 it('expires display/selection and rejects execution-capable payloads',async()=>{
  const {wrapper,api}=await setup();await settle(60001);expect(wrapper.get('[data-testid="live-grid-expired"]').text()).toContain('观察已过期');api.grid.mockResolvedValueOnce({...grid(),can_book:true});await wrapper.get('[data-testid="query-live-grid"]').trigger('click');await settle();expect(wrapper.text()).toContain('来源标记无效');expect(wrapper.find('[data-testid="live-availability-grid"]').exists()).toBe(false);
 });
 it('does not choose an unrelated category when badminton is missing',async()=>{
  const {wrapper,api}=await setup({categories:vi.fn(async()=>({...categories,options:[categories.options[0]]}))});expect(wrapper.text()).toContain('未返回唯一的羽毛球');expect(api.grid).not.toHaveBeenCalled();
 });
 it('makes no read when disabled',async()=>{
  const {wrapper,credentialApi,api}=await setup({options:vi.fn(async()=>({enabled:false}))});expect(wrapper.find('[data-testid="query-live-grid"]').exists()).toBe(false);expect(credentialApi.list).not.toHaveBeenCalled();expect(api.categories).not.toHaveBeenCalled();
 });
});
