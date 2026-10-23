import { afterEach, describe, expect, it, vi } from 'vitest';
import { flushPromises, mount, enableAutoUnmount } from '@vue/test-utils';
import { defineComponent, reactive, ref } from 'vue';
import ManualQueueGrid from './ManualQueueGrid.vue';
import ManualQueuePreview from './ManualQueuePreview.vue';
import ManualQueueWorkspace from './ManualQueueWorkspace.vue';
import BookingDateStrip from './BookingDateStrip.vue';
import PlanCredentialControl from './PlanCredentialControl.vue';
import { useManualQueue } from '../../composables/useManualQueue.js';

enableAutoUnmount(afterEach);afterEach(()=>vi.useRealTimers());
const entry=(court='1号场',duration=120,start='18:00',scope='羽毛球')=>({court_preference:court,duration_minutes:duration,start_time:start,end_time:`${String(Number(start.slice(0,2))+duration/60).padStart(2,'0')}:00`,scope_label:scope});
const queue=(entries,version=1)=>({version,target_date:'2026-10-20',candidates:entries.map(e=>({court_preferences:[e.court_preference],preferred_start_times:[e.start_time],duration_minutes:e.duration_minutes,query_scope_label:e.scope_label}))});
const session=()=>reactive({status:'authenticated',user:{user_id:'a'},csrfToken:'a',invalidationEpoch:0});
async function setup(overrides={},account=session()){
 const api={queue:vi.fn(async()=>({queue:null})),queues:vi.fn(async()=>({queues:[]})),saveQueue:vi.fn(async(_date,base,entries)=>({queue:queue(entries,base+1)})),...overrides};
 let state;const date=ref('2026-10-20'),credential=ref('credential-a');
 const wrapper=mount(defineComponent({setup(){state=useManualQueue(api,account,()=>date.value,()=>credential.value);return{};},template:'<div />'}));await flushPromises();return{state,api,account,date,credential,wrapper};
}

describe('manual queue interactions',()=>{
 it('waits for an in-flight autosave and flushes newer edits before leaving',async()=>{
  vi.useFakeTimers();const finishes=[];
  const {state,api}=await setup({saveQueue:vi.fn(()=>new Promise(resolve=>{finishes.push(resolve);}))});
  state.change([entry('1号场')]);await vi.advanceTimersByTimeAsync(450);
  let left=false;const leaving=state.flush().then(()=>{left=true;});await flushPromises();expect(left).toBe(false);
  state.change([entry('2号场')]);finishes[0]({queue:queue([entry('1号场')],1)});await flushPromises();
  expect(left).toBe(false);expect(api.saveQueue).toHaveBeenCalledTimes(2);
  finishes[1]({queue:queue([entry('2号场')],2)});await leaving;
  expect(left).toBe(true);expect(state.dirty).toBe(false);expect(state.version).toBe(2);
 });
 it('appends bounded history pages and resets the cursor when Token changes',async()=>{
  const queueRevisions=vi.fn().mockResolvedValueOnce({revisions:[{revision_id:'r3',revision_number:3}],next_before_version:3}).mockResolvedValueOnce({revisions:[{revision_id:'r2',revision_number:2}],next_before_version:null});
  const {state,credential}=await setup({queueRevisions});
  await state.showHistory('2026-10-20');await state.loadMoreHistory();
  expect(queueRevisions).toHaveBeenLastCalledWith('2026-10-20','credential-a',3);
  expect(state.history.map(row=>row.revision_number)).toEqual([3,2]);
  credential.value='credential-b';await flushPromises();expect(state.history).toBeNull();expect(state.historyCursor).toBeNull();
 });
 it('renders 09:00–22:00 and adds or cancels continuous hour candidates',async()=>{
  const wrapper=mount(ManualQueueGrid,{props:{courtNames:['已占用观察场','活动观察场'],entries:[],duration:120,scopeLabel:'羽毛球'}});
  expect(wrapper.findAll('tbody tr')).toHaveLength(13);
  expect(wrapper.find('tbody tr:first-child th').attributes('title')).toBe('09:00–10:00');
  expect(wrapper.find('tbody tr:last-child th').attributes('title')).toBe('21:00–22:00');
  expect(wrapper.find('tbody tr:first-child th').text()).toBe('09–10');
  expect(wrapper.find('tbody tr:last-child th').text()).toBe('21–22');
  await wrapper.get('[data-testid="queue-cell-9-0"]').trigger('click');
  expect(wrapper.emitted('change')[0][0]).toEqual([entry('已占用观察场')]);
  await wrapper.setProps({entries:[entry('已占用观察场')]});
  expect(wrapper.get('[data-testid="queue-cell-10-0"]').attributes('aria-pressed')).toBe('true');
  await wrapper.get('[data-testid="queue-cell-9-0"]').trigger('click');expect(wrapper.emitted('change').at(-1)[0]).toEqual([]);
  await wrapper.get('[data-testid="queue-cell-12-1"]').trigger('click');expect(wrapper.text()).toContain('两个连续小时');
  await wrapper.setProps({duration:60});await wrapper.get('[data-testid="queue-cell-12-1"]').trigger('click');expect(wrapper.emitted('change').at(-1)[0]).toContainEqual(entry('活动观察场',60,'21:00'));
 });
 it('reorders only inside its group and removes one candidate without affecting the other queue',async()=>{
  const wrapper=mount(ManualQueuePreview,{props:{entries:[entry('首选'),entry('备选'),entry('一小时',60)]}});
  await wrapper.get('[aria-label="将120分钟候选2上移"]').trigger('click');expect(wrapper.emitted('change')[0][0]).toEqual([entry('一小时',60),entry('备选'),entry('首选')]);
  await wrapper.get('[aria-label="移除120分钟候选1"]').trigger('click');expect(wrapper.emitted('change').at(-1)[0]).toEqual([entry('备选'),entry('一小时',60)]);
 });
 it('keeps the duration queues separate without a manual save form',async()=>{
  const state=reactive({entries:[entry('两小时'),entry('一小时',60)],statusText:'已自动保存',locked:false});
  const wrapper=mount(ManualQueueWorkspace,{props:{state,courtNames:['两小时','一小时'],scopeLabel:'羽毛球',targetDate:'2026-10-20'}});
  expect(wrapper.get('[data-testid="queue-two-hours"]').attributes('aria-pressed')).toBe('true');
  await wrapper.get('[data-testid="queue-one-hour"]').trigger('click');expect(wrapper.get('[data-testid="queue-one-hour"]').attributes('aria-pressed')).toBe('true');
  expect(wrapper.get('[data-testid="queue-120"]').text()).toContain('两小时');expect(wrapper.get('[data-testid="queue-60"]').text()).toContain('一小时');expect(wrapper.find('form').exists()).toBe(false);
 });
});

describe('weekday date strip',()=>{
 const state={business_timezone_name:'Asia/Shanghai',queryable_target_dates:['2026-10-15','2026-10-16','2026-10-17']};
 it('shows weekday labels and only one later queue date',async()=>{
  const wrapper=mount(BookingDateStrip,{props:{state,modelValue:'2026-10-15',extraDate:'2026-10-20'}});
  expect(wrapper.get('[data-testid="browse-date-0"]').text()).toContain('周四');
  expect(wrapper.get('[data-testid="browse-date-0"]').text()).toContain('10/15');
  expect(wrapper.findAll('[data-testid^="browse-date-"]')).toHaveLength(4);
  expect(wrapper.get('[data-testid="browse-date-extra"]').text()).toContain('周二');
  await wrapper.get('[data-testid="browse-date-extra"]').trigger('click');
  expect(wrapper.emitted('update:modelValue').at(-1)).toEqual(['2026-10-20']);
 });
 it('shows a selected custom date and hides the extra date when neither applies',()=>{
  const selected=mount(BookingDateStrip,{props:{state,modelValue:'2026-10-18'}});
  expect(selected.get('[data-testid="browse-date-extra"]').text()).toContain('周日');
  expect(selected.get('[data-testid="browse-date-extra"]').text()).toContain('10/18');
  const plain=mount(BookingDateStrip,{props:{state,modelValue:'2026-10-15'}});
  expect(plain.find('[data-testid="browse-date-extra"]').exists()).toBe(false);
 });
});

describe('automatic persistence',()=>{
 it('coalesces edits, preserves priority and uses returned base version',async()=>{
  vi.useFakeTimers();const {state,api}=await setup();state.change([entry('1h',60)]);state.change([entry('1h',60),entry('2h')]);
  expect(api.saveQueue).not.toHaveBeenCalled();await vi.advanceTimersByTimeAsync(451);await flushPromises();
  expect(api.saveQueue.mock.calls[0]).toEqual(['2026-10-20',0,[entry('2h'),entry('1h',60)],'credential-a']);expect(state.version).toBe(1);expect(state.dirty).toBe(false);
  state.change([entry('2h')]);await vi.advanceTimersByTimeAsync(451);expect(api.saveQueue.mock.calls[1][1]).toBe(1);
 });
 it('serializes changes during save rather than losing the later selection',async()=>{
  vi.useFakeTimers();let resolve;const {state,api}=await setup({saveQueue:vi.fn((_date,base,entries)=>base===0?new Promise(r=>{resolve=()=>r({queue:queue(entries,1)});}):Promise.resolve({queue:queue(entries,2)}))});
  state.change([entry()]);await vi.advanceTimersByTimeAsync(451);state.change([entry(),entry('backup')]);await vi.advanceTimersByTimeAsync(451);expect(api.saveQueue).toHaveBeenCalledOnce();resolve();await flushPromises();await vi.advanceTimersByTimeAsync(451);expect(api.saveQueue).toHaveBeenCalledTimes(2);expect(state.version).toBe(2);expect(state.entries).toHaveLength(2);
 });
 it('pauses on 409, preserves the local queue and adopts only explicitly',async()=>{
  vi.useFakeTimers();const {state,api}=await setup({saveQueue:vi.fn(async()=>{throw{status:409};})});state.change([entry('local')]);await vi.advanceTimersByTimeAsync(451);expect(state.blocked).toBe(true);expect(state.entries[0].court_preference).toBe('local');api.queue.mockResolvedValue({queue:queue([entry('remote')],2)});await state.inspectLatest();expect(state.entries[0].court_preference).toBe('local');state.adoptLatest();expect(state.entries[0].court_preference).toBe('remote');expect(api.saveQueue).toHaveBeenCalledOnce();
 });
 it('reconciles a lost successful response without duplicate write',async()=>{
  vi.useFakeTimers();const {state,api}=await setup({saveQueue:vi.fn(async()=>{throw{kind:'network'};})});state.change([entry()]);await vi.advanceTimersByTimeAsync(451);expect(state.dirty).toBe(true);api.queue.mockResolvedValue({queue:queue([entry()],1)});await state.inspectLatest();expect(state.version).toBe(1);expect(state.blocked).toBe(false);expect(api.saveQueue).toHaveBeenCalledOnce();
 });
 it('retains dirty semantic work across a same-user login redirect and allows explicit new revision',async()=>{
  vi.useFakeTimers();const initial=await setup();initial.state.change([entry('my pending intent')]);
  initial.account.user=null;initial.account.status='unauthenticated';await flushPromises();initial.wrapper.unmount();
  initial.account.user={user_id:'a'};initial.account.csrfToken='new';initial.account.status='authenticated';
  const restored=await setup({},initial.account);expect(restored.state.entries[0].court_preference).toBe('my pending intent');expect(restored.state.blocked).toBe(true);
  restored.state.saveLocalAgainstLatest();await vi.advanceTimersByTimeAsync(451);expect(restored.api.saveQueue).toHaveBeenCalledOnce();expect(restored.state.version).toBe(1);
 });
 it('suspends same-user dirty work and hides it from another user, ignoring late replies',async()=>{
  vi.useFakeTimers();let resolve;const {state,api,account}=await setup({saveQueue:vi.fn(()=>new Promise(r=>{resolve=r;}))});state.change([entry('A private')]);await vi.advanceTimersByTimeAsync(451);
  account.user=null;account.status='unauthenticated';await flushPromises();account.user={user_id:'b'};account.csrfToken='b';account.status='authenticated';await flushPromises();resolve({queue:queue([entry('A private')],1)});await flushPromises();expect(state.entries).toEqual([]);expect(state.version).toBe(0);
 });
});

describe('credential control',()=>{
 it('shows expiry metadata, switches owned credentials and clears a failed rotation token',async()=>{
  const account=session(),items=[{credential_id:'a',label:'A',enabled:true,validation_status:'validated',expiry_state:'active',token_expires_at_utc:'2026-10-20T00:00:00Z',credential_version:3,current_token_revision_id:'r3'},{credential_id:'b',label:'B',enabled:true,validation_status:'validated'}];
  const api={list:vi.fn(async()=>({credentials:items})),rotateToken:vi.fn(async()=>{throw{code:'credential_account_mismatch'};})};
  const wrapper=mount(PlanCredentialControl,{props:{api,session:account,modelValue:'a'},global:{stubs:{RouterLink:{template:'<a><slot /></a>'}}}});await flushPromises();expect(wrapper.get('[data-testid="token-expiry"]').text()).toContain('10/20');
  const details=wrapper.get('details');details.element.open=true;await details.trigger('toggle');await wrapper.get('[data-testid="selection-token"]').setValue('synthetic-test-token');await wrapper.get('form').trigger('submit');await flushPromises();expect(api.rotateToken).toHaveBeenCalledWith('a','synthetic-test-token',3,'r3');expect(wrapper.get('[data-testid="selection-token"]').element.value).toBe('');expect(wrapper.text()).toContain('不匹配');await wrapper.get('[data-testid="selection-credential"]').setValue('b');expect(wrapper.emitted('update:modelValue').at(-1)).toEqual(['b']);
 });
});
