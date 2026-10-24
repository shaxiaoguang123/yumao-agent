import { flushPromises, mount, enableAutoUnmount } from '@vue/test-utils';
import { reactive } from 'vue';
import { afterEach, describe, expect, it, vi } from 'vitest';
import ExecutionSnapshotPanel from './ExecutionSnapshotPanel.vue';

enableAutoUnmount(afterEach);
const entry={scope_label:'羽毛球',court_preference:'6号场',start_time:'09:00',end_time:'10:00',duration_minutes:60};
const run={
 run_id:'run-a',target_date:'2026-10-17',source_version:3,state:'ready',candidate_count:1,candidates:[entry],
 reconciliation:{retained_candidate_count:1,discarded_candidate_counts:{explicit_conflict:2}},
 stages:[{round_number:0,candidate_index:0,stage_key:'reconcile_booking_by_time',started_at_utc_ms:1792182600000,completed_at_utc_ms:1792182600150,elapsed_ms:150,outcome:'success',safe_code:null}],
};
const session=()=>reactive({status:'authenticated',user:{user_id:'owner'},invalidationEpoch:0});

describe('ExecutionSnapshotPanel',()=>{
 it('shows the separate filtered execution queue and stage timing',async()=>{
  const api={executionQueue:vi.fn(async()=>({run,worker_enabled:true}))};
  const wrapper=mount(ExecutionSnapshotPanel,{props:{api,credentialId:'credential-a',targetDate:'2026-10-17',session:session()}});
  await flushPromises();
  expect(api.executionQueue).toHaveBeenCalledWith('2026-10-17','credential-a');
  expect(wrapper.text()).toContain('已复核 · 等待 07:30');
  expect(wrapper.text()).toContain('explicit_conflict：2');
  await wrapper.get('summary').trigger('click');
  expect(wrapper.text()).toContain('6号场');
  expect(wrapper.text()).toContain('150 ms');
 });

 it('fences a late response after switching tokens',async()=>{
  let finish;
  const api={executionQueue:vi.fn((_date,id)=>id==='credential-a'?new Promise(resolve=>{finish=resolve;}):Promise.resolve({run:null,worker_enabled:true}))};
  const wrapper=mount(ExecutionSnapshotPanel,{props:{api,credentialId:'credential-a',targetDate:'2026-10-17',session:session()}});
  await flushPromises();
  await wrapper.setProps({credentialId:'credential-b'});await flushPromises();
  finish({run,worker_enabled:true});await flushPromises();
  expect(wrapper.text()).toContain('等待复核');
  expect(wrapper.text()).not.toContain('6号场');
 });
 it('clears loaded results on refresh and reports the new state to the plan card',async()=>{
  let finish;
  const api={executionQueue:vi.fn().mockResolvedValueOnce({run:{...run,state:'succeeded'},worker_enabled:true})
   .mockImplementationOnce(()=>new Promise(resolve=>{finish=resolve;}))};
  const wrapper=mount(ExecutionSnapshotPanel,{props:{api,credentialId:'credential-a',targetDate:'2026-10-17',session:session()}});
  await flushPromises();expect(wrapper.text()).toContain('抢票成功');
  await wrapper.setProps({refreshKey:1});
  expect(wrapper.text()).not.toContain('抢票成功');expect(wrapper.text()).toContain('读取中…');
  expect(wrapper.emitted('status-change').at(-1)[0]).toMatchObject({status:'loading',run:null});
  finish({run:null,worker_enabled:true});await flushPromises();
  expect(wrapper.text()).toContain('等待复核');
  expect(wrapper.emitted('status-change').at(-1)[0]).toMatchObject({status:'ready',run:null});
 });
 it('clears private execution data at session loss and discards the pending response',async()=>{
  let finish;const account=session();
  const api={executionQueue:vi.fn(()=>new Promise(resolve=>{finish=resolve;}))};
  const wrapper=mount(ExecutionSnapshotPanel,{props:{api,credentialId:'credential-a',targetDate:'2026-10-17',session:account}});
  account.status='unauthenticated';await flushPromises();
  finish({run:{...run,state:'succeeded'},worker_enabled:true});await flushPromises();
  expect(wrapper.find('details').exists()).toBe(false);expect(api.executionQueue).toHaveBeenCalledTimes(1);
  expect(wrapper.emitted('status-change').at(-1)[0]).toMatchObject({status:'unavailable',run:null});
 });
});
