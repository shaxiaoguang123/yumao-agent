import { mount, flushPromises, enableAutoUnmount } from '@vue/test-utils';
import { reactive } from 'vue';
import { afterEach, describe, expect, it, vi } from 'vitest';
import TicketQueuePlans from './TicketQueuePlans.vue';

enableAutoUnmount(afterEach);
const candidate={duration_minutes:120,court_preferences:['一号场'],preferred_start_times:['18:00']};
const q=(date,extra={})=>{const version=extra.version??2;return{plan_id:date,version,current_revision_id:`${date}-revision-${version}`,target_date:date,credential_id:'credential-a',candidates:[candidate],...extra};};
const storedQueue=(date,version,entries,credential_id)=>q(date,{version,credential_id,candidates:entries.map(entry=>({duration_minutes:entry.duration_minutes,court_preferences:[entry.court_preference],preferred_start_times:[entry.start_time],query_scope_label:entry.scope_label||''}))});
const executionRun=(queue,extra={})=>({run_id:'run-a',target_date:queue.target_date,source_plan_id:queue.plan_id,source_revision_id:queue.current_revision_id,source_version:queue.version,state:'succeeded',candidate_count:0,candidates:[],reconciliation:{retained_candidate_count:0},stages:[],...extra});
const calendarState={business_date:'2026-10-15',queryable_target_dates:['2026-10-15','2026-10-16','2026-10-17']};
async function setup({queues, ...overrides}={}){
 const api={removeQueue:vi.fn(async()=>({})),saveQueue:vi.fn(async(date,version,entries,credential)=>({queue:storedQueue(date,version+1,entries,credential)})),...overrides};
 const account=reactive({status:'authenticated',user:{user_id:'a'},csrfToken:'a'});
 const wrapper=mount(TicketQueuePlans,{props:{queues:queues||[q('2026-10-12',{plan_status:'expired',can_open_selection:false}),q('2026-10-16'),q('2026-10-20',{can_open_selection:false})],calendarState,api,session:account,courtNames:['一号场','二号场']}});return{wrapper,api,account};
}
describe('ticket plan management',()=>{
 it('shows a successful execution on the matching plan card using the existing snapshot read',async()=>{
  const queue=q('2026-10-16');
  const executionQueue=vi.fn(async()=>({run:executionRun(queue),worker_enabled:true}));
  const {wrapper}=await setup({queues:[queue],executionQueue});await flushPromises();
  expect(wrapper.get('.ticket-state').text()).toBe('已执行 · 抢票成功');
  expect(wrapper.get('.ticket-state').classes()).toContain('is-success');
  expect(wrapper.get('.execution-snapshot summary').text()).toContain('已执行 · 抢票成功');
  expect(executionQueue).toHaveBeenCalledTimes(1);
 });
 it.each([
  ['ready','已复核 · 等待 07:30'],['calibrated','时间已校准 · 等待执行'],
  ['running','执行中'],['failed','三轮未成功'],['empty','复核后没有可执行候选'],
  ['stale','保存队列已变更'],['needs_attention','需要关注'],['unrecognized','状态未知'],
 ])('shows %s instead of claiming the queue has not run',async(state,label)=>{
  const queue=q('2026-10-16');
  const {wrapper}=await setup({queues:[queue],executionQueue:vi.fn(async()=>({run:executionRun(queue,{state}),worker_enabled:true}))});
  await flushPromises();expect(wrapper.get('.ticket-state').text()).toBe(label);
 });
 it('does not label a modified queue as the successful older revision',async()=>{
  const queue=q('2026-10-16');
  const {wrapper}=await setup({queues:[queue],executionQueue:vi.fn(async()=>({run:executionRun(queue,{source_version:1,source_revision_id:'revision-1'}),worker_enabled:true}))});
  await flushPromises();
  expect(wrapper.get('.ticket-state').text()).toBe('队列已修改 · 执行记录来自 v1');
  expect(wrapper.get('.ticket-state').classes()).not.toContain('is-success');
 });
 it('rejects an execution result belonging to a different plan',async()=>{
  const queue=q('2026-10-16');
  const {wrapper}=await setup({queues:[queue],executionQueue:vi.fn(async()=>({run:executionRun(queue,{source_plan_id:'another-plan'}),worker_enabled:true}))});
  await flushPromises();expect(wrapper.get('.ticket-state').text()).toBe('执行状态读取失败');
  expect(wrapper.text()).not.toContain('抢票成功');
 });
 it.each([{source_version:undefined},{source_version:0},{source_revision_id:''}])('does not infer success from missing source metadata: %s',async metadata=>{
  const queue=q('2026-10-16');
  const {wrapper}=await setup({queues:[queue],executionQueue:vi.fn(async()=>({run:executionRun(queue,metadata),worker_enabled:true}))});
  await flushPromises();expect(wrapper.get('.ticket-state').text()).toBe('执行状态读取失败');
  expect(wrapper.text()).not.toContain('抢票成功');
 });
 it('refreshes the execution when the plan list is reloaded without a version change',async()=>{
  const queue=q('2026-10-16');
  const executionQueue=vi.fn().mockResolvedValueOnce({run:executionRun(queue,{state:'running'}),worker_enabled:true})
   .mockResolvedValueOnce({run:executionRun(queue),worker_enabled:true});
  const {wrapper}=await setup({queues:[queue],executionQueue});await flushPromises();
  expect(wrapper.get('.ticket-state').text()).toBe('执行中');
  await wrapper.setProps({queues:[{...queue}]});await flushPromises();
  expect(wrapper.get('.ticket-state').text()).toBe('已执行 · 抢票成功');
  expect(executionQueue).toHaveBeenCalledTimes(2);
 });
 it('does not retain success or claim nonexecution after a failed refresh',async()=>{
  const queue=q('2026-10-16');
  const executionQueue=vi.fn().mockResolvedValueOnce({run:executionRun(queue),worker_enabled:true})
   .mockRejectedValueOnce(new Error('network'));
  const {wrapper}=await setup({queues:[queue],executionQueue});await flushPromises();
  await wrapper.setProps({queues:[{...queue}]});await flushPromises();
  expect(wrapper.get('.ticket-state').text()).toBe('执行状态读取失败');
  expect(wrapper.text()).not.toContain('抢票成功');
  expect(wrapper.get('.ticket-state').text()).not.toContain('未执行');
 });
 it('fences a late successful execution after an account change',async()=>{
  const queue=q('2026-10-16');let finish;
  const executionQueue=vi.fn().mockImplementationOnce(()=>new Promise(resolve=>{finish=resolve;}))
   .mockResolvedValue({run:null,worker_enabled:true});
  const {wrapper,account}=await setup({queues:[queue],executionQueue});await flushPromises();
  account.user={user_id:'b'};await flushPromises();
  finish({run:executionRun(queue),worker_enabled:true});await flushPromises();
  expect(wrapper.get('.ticket-state').text()).toBe('未执行');
  expect(wrapper.text()).not.toContain('抢票成功');
 });
 it('keeps a confirmed success visible after the reservation date',async()=>{
  const queue=q('2026-10-14',{plan_status:'expired'});
  const {wrapper}=await setup({queues:[queue],executionQueue:vi.fn(async()=>({run:executionRun(queue),worker_enabled:true}))});
  await flushPromises();expect(wrapper.get('.ticket-state').text()).toBe('已执行 · 抢票成功');
 });
 it('reads fresh execution state on each visit without querying the hidden plan tab',async()=>{
  const queue=q('2026-10-16');
  const executionQueue=vi.fn().mockResolvedValueOnce({run:executionRun(queue,{state:'ready'}),worker_enabled:true})
   .mockResolvedValueOnce({run:executionRun(queue),worker_enabled:true});
  const account=reactive({status:'authenticated',user:{user_id:'a'}});
  const wrapper=mount(TicketQueuePlans,{props:{queues:[queue],calendarState,api:{executionQueue},session:account,active:false}});
  await flushPromises();expect(executionQueue).not.toHaveBeenCalled();
  await wrapper.setProps({active:true});await flushPromises();
  expect(wrapper.get('.ticket-state').text()).toBe('已复核 · 等待 07:30');
  await wrapper.setProps({active:false});await wrapper.setProps({active:true});await flushPromises();
  expect(wrapper.get('.ticket-state').text()).toBe('已执行 · 抢票成功');expect(executionQueue).toHaveBeenCalledTimes(2);
 });
 it('keeps arbitrary-date plans visible but limits the quick continue action to the three-day window',async()=>{
  const {wrapper}=await setup({queues:[q('2026-10-20',{can_open_selection:false}),q('2026-10-16'),q('2026-10-14',{plan_status:'expired',can_open_selection:false}),q('2026-10-13')]});
  expect(wrapper.findAll('article').map(article=>article.text().match(/2026-10-\d{2}/)?.[0])).toEqual(['2026-10-14','2026-10-16','2026-10-20']);
  expect(wrapper.text()).toContain('已过期');expect(wrapper.text()).not.toContain('已执行');
  expect(wrapper.get('[aria-label="2026-10-20继续选择"]').element.disabled).toBe(true);
  await wrapper.get('[aria-label="2026-10-20继续选择"]').trigger('click');expect(wrapper.emitted('select')).toBeUndefined();
  await wrapper.get('[aria-label="调整2026-10-20队列顺序和场地"]').trigger('click');expect(wrapper.get('.ticket-inline-editor').exists()).toBe(true);
  expect(wrapper.emitted('select')).toBeUndefined();await wrapper.get('[aria-label="取消2026-10-20队列调整"]').trigger('click');
  await wrapper.get('[aria-label="2026-10-16继续选择"]').trigger('click');expect(wrapper.emitted('select')[0]).toEqual(['2026-10-16','credential-a']);
  await wrapper.setProps({dateFilter:'2026-10-14'});expect(wrapper.findAll('article')).toHaveLength(1);expect(wrapper.text()).toContain('2026-10-14');
  await wrapper.setProps({dateFilter:'2026-10-13'});expect(wrapper.findAll('article')).toHaveLength(0);
 });
 it('reorders and removes a candidate in the plan card, then saves with the scoped queue version',async()=>{
  const queue=q('2026-10-16',{candidates:[
   {duration_minutes:120,court_preferences:['2号场'],preferred_start_times:['16:00'],query_scope_label:'羽毛球'},
   {duration_minutes:120,court_preferences:['4号场'],preferred_start_times:['18:00'],query_scope_label:'羽毛球'},
  ]});
  const {wrapper,api}=await setup({queues:[queue]});
  await wrapper.get('[aria-label="调整2026-10-16队列顺序和场地"]').trigger('click');
  await wrapper.get('[aria-label="将120分钟候选2上移"]').trigger('click');
  expect(wrapper.findAll('.queue-entry strong').map(node=>node.text())).toEqual(['4号场','2号场']);
  await wrapper.get('[aria-label="移除120分钟候选2"]').trigger('click');
  expect(wrapper.findAll('.queue-entry strong').map(node=>node.text())).toEqual(['4号场']);
  await wrapper.get('.ticket-inline-editor .primary-button').trigger('click');await flushPromises();
  expect(api.saveQueue).toHaveBeenCalledWith('2026-10-16',2,[{
   court_preference:'4号场',start_time:'18:00',end_time:'20:00',duration_minutes:120,scope_label:'羽毛球',
  }],'credential-a');
  expect(wrapper.findAll('.queue-entry strong').map(node=>node.text())).toEqual(['4号场']);
  expect(wrapper.text()).toContain('队列调整已保存');
  expect(wrapper.emitted('changed')[0]).toEqual(['2026-10-16']);
 });
 it('preserves inline changes after a version conflict until cancelled',async()=>{
  const {wrapper}=await setup({queues:[q('2026-10-16')],saveQueue:vi.fn().mockRejectedValue({status:409})});
  await wrapper.get('[aria-label="调整2026-10-16队列顺序和场地"]').trigger('click');
  await wrapper.get('[aria-label="移除120分钟候选1"]').trigger('click');
  await wrapper.get('.ticket-inline-editor .primary-button').trigger('click');await flushPromises();
  expect(wrapper.get('.ticket-inline-editor [role="alert"]').text()).toContain('队列版本已变化');
  expect(wrapper.findAll('.queue-entry strong')).toHaveLength(0);
  await wrapper.get('[aria-label="取消2026-10-16队列调整"]').trigger('click');
  expect(wrapper.findAll('.queue-entry strong').map(node=>node.text())).toEqual(['一号场']);
 });
 it('keeps legacy unbound queues readable and prevents editing them under the wrong Token',async()=>{
  const legacy=q('2026-10-20',{credential_id:null});const {wrapper}=await setup();await wrapper.setProps({queues:[legacy]});
  expect(wrapper.text()).toContain('历史未关联凭据');expect(wrapper.get('[aria-label="调整2026-10-20队列顺序和场地"]').element.disabled).toBe(true);
  expect(wrapper.get('[aria-label="2026-10-20版本历史"]').element.disabled).toBe(false);
 });
 it('shows a cleared date plan and its history only when that date is selected',async()=>{
  const {wrapper}=await setup({queues:[q('2026-10-16',{candidates:[]})]});expect(wrapper.findAll('article')).toHaveLength(0);
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
