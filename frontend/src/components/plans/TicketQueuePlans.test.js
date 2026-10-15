import { mount, flushPromises, enableAutoUnmount } from '@vue/test-utils';
import { reactive } from 'vue';
import { afterEach, describe, expect, it, vi } from 'vitest';
import TicketQueuePlans from './TicketQueuePlans.vue';

enableAutoUnmount(afterEach);
const candidate={duration_minutes:120,court_preferences:['一号场'],preferred_start_times:['18:00']};
const q=(date,extra={})=>({plan_id:date,version:2,target_date:date,credential_id:'credential-a',candidates:[candidate],...extra});
const calendarState={business_date:'2026-10-15',queryable_target_dates:['2026-10-15','2026-10-16','2026-10-17']};
async function setup(overrides={}){
 const api={removeQueue:vi.fn(async()=>({})),...overrides};
 const account=reactive({status:'authenticated',user:{user_id:'a'},csrfToken:'a'});
 const wrapper=mount(TicketQueuePlans,{props:{queues:[q('2026-10-12',{plan_status:'expired',can_open_selection:false}),q('2026-10-16'),q('2026-10-20',{can_open_selection:false})],calendarState,api,session:account,courtNames:['一号场','二号场']}});return{wrapper,api,account};
}
describe('ticket plan management',()=>{
 it('keeps arbitrary-date plans visible but limits the quick continue action to the three-day window',async()=>{
  const {wrapper}=await setup();expect(wrapper.findAll('article')).toHaveLength(3);expect(wrapper.text()).toContain('已过期');expect(wrapper.text()).not.toContain('已执行');
  expect(wrapper.get('[aria-label="2026-10-20继续选择"]').element.disabled).toBe(true);
  await wrapper.get('[aria-label="2026-10-20继续选择"]').trigger('click');expect(wrapper.emitted('select')).toBeUndefined();
  await wrapper.get('[aria-label="编辑2026-10-20队列"]').trigger('click');expect(wrapper.emitted('select')[0]).toEqual(['2026-10-20','credential-a']);
  await wrapper.get('[aria-label="2026-10-16继续选择"]').trigger('click');expect(wrapper.emitted('select')[1]).toEqual(['2026-10-16','credential-a']);
  await wrapper.setProps({dateFilter:'2026-10-12'});expect(wrapper.findAll('article')).toHaveLength(1);expect(wrapper.text()).toContain('2026-10-12');await wrapper.setProps({dateFilter:'2026-10-01'});expect(wrapper.findAll('article')).toHaveLength(0);
 });
 it('routes editing through the shared selection screen rather than rendering a second editor',async()=>{
  const {wrapper}=await setup();await wrapper.get('[aria-label="编辑2026-10-16队列"]').trigger('click');
  expect(wrapper.emitted('select')[0]).toEqual(['2026-10-16','credential-a']);expect(wrapper.find('form').exists()).toBe(false);
 });
 it('keeps legacy unbound queues readable and prevents editing them under the wrong Token',async()=>{
  const legacy=q('2026-10-20',{credential_id:null});const {wrapper}=await setup();await wrapper.setProps({queues:[legacy]});
  expect(wrapper.text()).toContain('历史未关联凭据');expect(wrapper.get('[aria-label="编辑2026-10-20队列"]').element.disabled).toBe(true);
  expect(wrapper.get('[aria-label="2026-10-20版本历史"]').element.disabled).toBe(false);
 });
 it('shows a cleared date plan and its history only when that date is selected',async()=>{
  const {wrapper}=await setup();await wrapper.setProps({queues:[q('2026-10-16',{candidates:[]})]});expect(wrapper.findAll('article')).toHaveLength(0);
  await wrapper.setProps({dateFilter:'2026-10-16'});expect(wrapper.findAll('article')).toHaveLength(1);expect(wrapper.text()).toContain('候选已清空');
  await wrapper.get('[aria-label="2026-10-16版本历史"]').trigger('click');expect(wrapper.emitted('history')[0]).toEqual(['2026-10-16','credential-a']);
 });
 it('requires explicit delete confirmation and sends the selected credential scope',async()=>{
  const {wrapper,api}=await setup();await wrapper.get('[aria-label="删除2026-10-16队列"]').trigger('click');expect(api.removeQueue).not.toHaveBeenCalled();
  await wrapper.findAll('button').find(button=>button.text()==='确认删除').trigger('click');await flushPromises();
  expect(api.removeQueue).toHaveBeenCalledWith('2026-10-16',2,'credential-a');expect(wrapper.emitted('changed')[0]).toEqual(['2026-10-16']);
 });
 it('fences a late delete response when the account changes',async()=>{
  let finish;const {wrapper,account}=await setup({removeQueue:vi.fn(()=>new Promise(resolve=>{finish=resolve;}))});
  await wrapper.get('[aria-label="删除2026-10-16队列"]').trigger('click');await wrapper.findAll('button').find(button=>button.text()==='确认删除').trigger('click');
  account.user={user_id:'b'};await flushPromises();finish({});await flushPromises();expect(wrapper.emitted('changed')).toBeUndefined();
 });
});
