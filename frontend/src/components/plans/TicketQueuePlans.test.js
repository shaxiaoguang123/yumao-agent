import { mount, flushPromises, enableAutoUnmount } from '@vue/test-utils';
import { reactive } from 'vue';
import { afterEach, describe, expect, it, vi } from 'vitest';
import TicketQueuePlans from './TicketQueuePlans.vue';
enableAutoUnmount(afterEach);
const candidate={duration_minutes:120,court_preferences:['一号场'],preferred_start_times:['18:00']};
const q=(date,extra={})=>({plan_id:date,version:2,target_date:date,candidates:[candidate],...extra});
const calendarState={business_date:'2026-10-15',queryable_target_dates:['2026-10-15','2026-10-16','2026-10-17']};
async function setup(overrides={}){
 const api={saveQueue:vi.fn(async()=>({})),removeQueue:vi.fn(async()=>({})),...overrides};
 const account=reactive({status:'authenticated',user:{user_id:'a'},csrfToken:'a'});
 const wrapper=mount(TicketQueuePlans,{props:{queues:[q('2026-10-12',{plan_status:'expired',can_open_selection:false}),q('2026-10-16'),q('2026-10-20',{can_open_selection:false})],calendarState,api,session:account,courtNames:['一号场','二号场']}});return{wrapper,api,account};
}
describe('ticket plan management',()=>{
 it('filters arbitrary dates and limits selection jumps to the server three-day window',async()=>{
  const {wrapper}=await setup();expect(wrapper.findAll('article')).toHaveLength(3);expect(wrapper.text()).toContain('已过期');expect(wrapper.text()).not.toContain('已执行');
  expect(wrapper.get('[aria-label="2026-10-20继续选择"]').element.disabled).toBe(true);expect(wrapper.get('[aria-label="2026-10-12继续选择"]').element.disabled).toBe(true);
  await wrapper.get('[aria-label="2026-10-16继续选择"]').trigger('click');expect(wrapper.emitted('select')[0]).toEqual(['2026-10-16']);
  await wrapper.setProps({dateFilter:'2026-10-12'});expect(wrapper.findAll('article')).toHaveLength(1);expect(wrapper.text()).toContain('2026-10-12');await wrapper.setProps({dateFilter:'2026-10-01'});expect(wrapper.text()).toContain('当天没有人工计划');
 });
 it('shows a cleared date plan with history access when that exact date is selected',async()=>{
  const {wrapper}=await setup();await wrapper.setProps({queues:[q('2026-10-16',{candidates:[]})]});expect(wrapper.findAll('article')).toHaveLength(0);await wrapper.setProps({dateFilter:'2026-10-16'});expect(wrapper.findAll('article')).toHaveLength(1);expect(wrapper.text()).toContain('已清空');await wrapper.get('[aria-label="2026-10-16版本历史"]').trigger('click');expect(wrapper.emitted('history')[0]).toEqual(['2026-10-16']);
 });
 it('edits historical semantic candidates with CAS and preserves content on conflict',async()=>{
  const {wrapper,api}=await setup({saveQueue:vi.fn(async()=>{throw{status:409};})});await wrapper.get('[aria-label="编辑2026-10-12队列"]').trigger('click');
  await wrapper.get('[aria-label="候选1开始时间"]').setValue('07:00');await wrapper.get('[aria-label="候选1场地"]').setValue('二号场');await wrapper.get('form').trigger('submit');await flushPromises();
  expect(api.saveQueue).toHaveBeenCalledWith('2026-10-12',2,[{duration_minutes:120,court_preference:'二号场',start_time:'07:00',end_time:'09:00'}]);expect(wrapper.text()).toContain('版本冲突');expect(wrapper.get('[aria-label="候选1开始时间"]').element.value).toBe('07:00');
 });
 it('requires explicit delete confirmation and sends the owned current version',async()=>{
  const {wrapper,api}=await setup();await wrapper.get('[aria-label="删除2026-10-16队列"]').trigger('click');expect(api.removeQueue).not.toHaveBeenCalled();await wrapper.findAll('button').find(b=>b.text()==='确认删除').trigger('click');await flushPromises();expect(api.removeQueue).toHaveBeenCalledWith('2026-10-16',2);expect(wrapper.emitted('changed')[0]).toEqual(['2026-10-16']);
 });
 it('clears editor secrets-free drafts when the account changes and ignores late writes',async()=>{
  let finish;const {wrapper,api,account}=await setup({saveQueue:vi.fn(()=>new Promise(r=>{finish=r;}))});await wrapper.get('[aria-label="编辑2026-10-16队列"]').trigger('click');await wrapper.get('form').trigger('submit');account.user={user_id:'b'};await flushPromises();finish({});await flushPromises();expect(wrapper.find('form').exists()).toBe(false);expect(wrapper.emitted('changed')).toBeUndefined();
 });
});
