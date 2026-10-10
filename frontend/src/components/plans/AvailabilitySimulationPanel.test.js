import { flushPromises, mount, enableAutoUnmount } from '@vue/test-utils';
import { reactive } from 'vue';
import { afterEach, describe, expect, it, vi } from 'vitest';
import AvailabilitySimulationPanel from './AvailabilitySimulationPanel.vue';
import { plan } from './testFixtures.js';

enableAutoUnmount(afterEach);
const scenarios=[{id:'complete',name:'完整可用',description:'完整合成数据'},{id:'partially_occupied',name:'部分占用',description:'第一偏好部分占用'},{id:'no_match',name:'全部不可用',description:'无匹配'}];
const source={simulation:true,trust_state:'synthetic',target_date:'2026-10-20',timezone_name:'Asia/Shanghai'};
function response(changes={}){
 return {mode:'simulation',simulation:true,plan_id:'synthetic-plan',base_version:1,source,scope_note:'人工文本仅作合成标签',reason_summary:[],candidates:[{
  rank:1,court_name:'6号场',start_time:'18:00',end_time:'20:00',duration_minutes:120,price:{total_minor:6000,currency_code:'CNY',minor_unit_exponent:2},
  fallback:{lower_priority_time:false,lower_priority_court:false,other_court:false,time_shift:false},match_reasons:['完整覆盖120分钟'],
 }],...changes};
}
function fixture(overrides={}){
 return {options:vi.fn(async()=>({enabled:true,scenarios})),match:vi.fn(async()=>response()),...overrides};
}
async function setup(api=fixture(),plans=[plan()]){
 const session=reactive({status:'authenticated',user:{user_id:'a'},csrfToken:'csrf-a'});
 const wrapper=mount(AvailabilitySimulationPanel,{props:{api,session,plans}});await flushPromises();return {wrapper,api,session};
}
async function match(wrapper){await wrapper.get('[data-testid="simulation-plan"]').setValue('synthetic-plan');await wrapper.get('[data-testid="simulate-matches"]').trigger('click');await flushPromises();}

describe('saved plan simulation',()=>{
 it('requires a saved plan and explicit click, labels synthetic inventory clearly',async()=>{
  const {wrapper,api}=await setup();expect(api.match).not.toHaveBeenCalled();expect(wrapper.get('[data-testid="simulate-matches"]').element.disabled).toBe(true);
  expect(wrapper.text()).toContain('并非真实场馆库存');await match(wrapper);expect(api.match).toHaveBeenCalledWith('synthetic-plan',1,'complete');expect(wrapper.text()).toContain('第 1 顺位 · 6号场');expect(wrapper.text()).toContain('60.00 CNY');expect(wrapper.text()).toContain('首选时间与场地');expect(wrapper.text()).toContain('候选建议未预订');
 });
 it('shows backup court and authorized shift independently from initial preferences',async()=>{
  const answer=response();answer.candidates[0]={...answer.candidates[0],court_name:'5号场',fallback:{lower_priority_court:true,time_shift:true}};
  const {wrapper,api}=await setup(fixture({match:vi.fn(async()=>answer)}));await wrapper.get('[data-testid="simulation-scenario"]').setValue('partially_occupied');await match(wrapper);
  expect(api.match).toHaveBeenCalledWith('synthetic-plan',1,'partially_occupied');expect(wrapper.text()).toContain('使用备选场地偏好');expect(wrapper.text()).toContain('使用授权时间浮动');
 });
 it('explains empty results and clears stale results when the scenario changes',async()=>{
  const {wrapper}=await setup(fixture({match:vi.fn(async()=>response({candidates:[],reason_summary:[{code:'time_discontinuous',message:'时段断档',count:1},{code:'over_budget',message:'超过预算',count:2}]}))}));await match(wrapper);
  expect(wrapper.text()).toContain('没有符合当前计划的候选时段');expect(wrapper.text()).toContain('时段断档');expect(wrapper.text()).toContain('超过预算');expect(wrapper.get('details').attributes('open')).toBeDefined();await wrapper.get('[data-testid="simulation-scenario"]').setValue('no_match');expect(wrapper.find('[aria-label="模拟匹配结果"]').exists()).toBe(false);
 });
 it('does not treat missing prices as zero',async()=>{
  const answer=response();answer.candidates[0].price=null;const {wrapper}=await setup(fixture({match:vi.fn(async()=>answer)}));await match(wrapper);expect(wrapper.text()).toContain('价格未确认');expect(wrapper.text()).not.toContain('0.00 CNY');
 });
 it('renders disabled environment, empty plans and failed options without changing manual planning',async()=>{
  const disabled=await setup(fixture({options:vi.fn(async()=>({enabled:false,scenarios:[]}))}));expect(disabled.wrapper.text()).toContain('本环境未启用');expect(disabled.wrapper.find('[data-testid="simulate-matches"]').exists()).toBe(false);
  const empty=await setup(fixture(),[]);expect(empty.wrapper.text()).toContain('确认保存');expect(empty.wrapper.get('[data-testid="simulate-matches"]').element.disabled).toBe(true);
  const failed=await setup(fixture({options:vi.fn(async()=>{throw new Error('synthetic network');})}));expect(failed.wrapper.text()).toContain('模拟场景读取失败');
 });
 it('preserves selection on network error and requests a list refresh on stale version',async()=>{
  const api=fixture({match:vi.fn().mockRejectedValueOnce({kind:'network'}).mockRejectedValueOnce({code:'plan_version_conflict'})});const {wrapper}=await setup(api);await match(wrapper);expect(wrapper.text()).toContain('预约计划未被修改');expect(wrapper.get('[data-testid="simulation-plan"]').element.value).toBe('synthetic-plan');
  await wrapper.get('[data-testid="simulate-matches"]').trigger('click');await flushPromises();expect(wrapper.text()).toContain('计划版本已变化');await wrapper.findAll('button').find(b=>b.text()==='刷新计划列表').trigger('click');expect(wrapper.emitted('refresh-request')).toHaveLength(1);
 });
 it('refuses unlabelled live data and clears results after a saved version changes',async()=>{
  const {wrapper,api}=await setup(fixture({match:vi.fn().mockResolvedValueOnce(response({simulation:false})).mockResolvedValueOnce(response())}));await match(wrapper);expect(wrapper.text()).toContain('已停止展示');expect(wrapper.find('[aria-label="模拟匹配结果"]').exists()).toBe(false);
  await wrapper.get('[data-testid="simulate-matches"]').trigger('click');await flushPromises();expect(wrapper.find('[aria-label="模拟匹配结果"]').exists()).toBe(true);await wrapper.setProps({plans:[plan(2)]});expect(wrapper.find('[aria-label="模拟匹配结果"]').exists()).toBe(false);expect(api.match).toHaveBeenCalledTimes(2);
 });
 it('fences late matching results and clears context when the user changes',async()=>{
  let resolve;const {wrapper,session}=await setup(fixture({match:vi.fn(()=>new Promise(r=>{resolve=r;}))}));await wrapper.get('[data-testid="simulation-plan"]').setValue('synthetic-plan');await wrapper.get('[data-testid="simulate-matches"]').trigger('click');session.user={user_id:'b'};await flushPromises();resolve(response());await flushPromises();expect(wrapper.find('[aria-label="模拟匹配结果"]').exists()).toBe(false);expect(wrapper.get('[data-testid="simulation-plan"]').element.value).toBe('');
 });
});
