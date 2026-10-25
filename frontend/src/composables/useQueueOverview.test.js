import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils';
import { defineComponent, reactive } from 'vue';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { useQueueOverview } from './useQueueOverview.js';
enableAutoUnmount(afterEach);
afterEach(()=>vi.useRealTimers());
const queue=(id,state='waiting')=>({record_id:id,candidates:[],lifecycle:{state,category:'pending',opening_at_utc_ms:0}});
const result=(queues=[],page=1,next_page=null)=>({queues,counts:{pending:2,succeeded:0,attention:0,all:2},total:2,page,next_page});
function setup(api){
 const session=reactive({status:'authenticated',user:{user_id:'a'},csrfToken:'a'});
 const selection=reactive({credentialId:'token-a',category:'pending',targetDate:'',active:true,refreshKey:0});let state;
 const wrapper=mount(defineComponent({setup(){state=useQueueOverview(api,session,()=>selection);return{};},template:'<div />'}));
 return {session,selection,state,wrapper};
}
describe('queue summary reads',()=>{
 it('paginates without duplicates and retries a failed page without losing earlier results',async()=>{
  const api={queueOverview:vi.fn().mockResolvedValueOnce(result([queue('a')],1,2)).mockRejectedValueOnce(Error()).mockResolvedValueOnce(result([queue('a'),queue('b')],2))};
  const {state}=setup(api);await flushPromises();await state.more();expect(state.queues.map(q=>q.record_id)).toEqual(['a']);
  expect(state.message).toContain('不能判断');await state.more();expect(state.queues.map(q=>q.record_id)).toEqual(['a','b']);expect(state.nextPage).toBeNull();
  expect(api.queueOverview.mock.calls[2][1].page).toBe(2);
 });
 it('fences late Token and session responses and cancels requests',async()=>{
  let finish;const api={queueOverview:vi.fn().mockImplementationOnce(()=>new Promise(resolve=>finish=resolve)).mockResolvedValue(result([queue('b')]))};
  const {selection,session,state}=setup(api);selection.credentialId='token-b';await flushPromises();
  expect(api.queueOverview.mock.calls[0][2].signal.aborted).toBe(true);finish(result([queue('private-a')]));await flushPromises();
  expect(state.queues.map(q=>q.record_id)).toEqual(['b']);session.status='unauthenticated';await flushPromises();expect(state.queues).toEqual([]);expect(state.counts).toBeNull();
 });
 it('sends all filters, does no hidden reads and rejects malformed pagination',async()=>{
  const api={queueOverview:vi.fn(async()=>result())};const {selection,state}=setup(api);await flushPromises();
  selection.active=false;selection.targetDate='2026-10-27';selection.category='succeeded';await flushPromises();expect(api.queueOverview).toHaveBeenCalledOnce();
  api.queueOverview.mockResolvedValueOnce({...result(),next_page:1});selection.active=true;await flushPromises();expect(state.status).toBe('error');
  expect(api.queueOverview).toHaveBeenLastCalledWith('token-a',{category:'succeeded',target_date:'2026-10-27',page:1,limit:20},expect.objectContaining({signal:expect.any(AbortSignal)}));
 });
 it('refreshes active running queues and clears the timer on unmount',async()=>{
  vi.useFakeTimers();const api={queueOverview:vi.fn(async()=>result([queue('a','running')]))};const {wrapper}=setup(api);await flushPromises();
  await vi.advanceTimersByTimeAsync(15000);expect(api.queueOverview).toHaveBeenCalledTimes(2);
  wrapper.unmount();await vi.advanceTimersByTimeAsync(30000);expect(api.queueOverview).toHaveBeenCalledTimes(2);
 });
});
