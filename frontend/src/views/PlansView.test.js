import { flushPromises, mount, enableAutoUnmount } from '@vue/test-utils';
import { reactive } from 'vue';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { context, intent, plan, windowState } from '../components/plans/testFixtures.js';

enableAutoUnmount(afterEach);
const clone=(v)=>structuredClone(v);
function apiFixture(overrides={}) { return {list:vi.fn(async()=>({plans:[plan()]})),options:vi.fn(async()=>({catalog_status:'not_configured',catalog_version:null,source_state:'protocol_evidence_partial',venues:[],capabilities:{display:false,plan_binding:false,historical_availability:false,live_availability:false},evidence_readiness:{venue_directory_display:false,venue_catalog:false,plan_binding:false,recorded_availability:false,price_aware_matching:false,live_read_only_query:false},blocking_evidence:['client_version_association','venue_list_response','venue_name_to_parent_scope'],binding_blocking_evidence:['client_version_association','venue_list_response','venue_name_to_parent_scope','court_to_venue_association'],availability_blocking_evidence:['client_version_association','venue_list_response','venue_name_to_parent_scope','court_to_venue_association','booking_by_time_scope_response_association','booking_by_time_response_structure','availability_status_semantics','conflict_list_semantics','time_atom_duration_continuity'],context:clone(context)})),window:vi.fn(async()=>clone(windowState)),get:vi.fn(async()=>({plan:plan(2,{venue_preference:'另一个窗口保存'})})),create:vi.fn(async(value)=>({plan:plan(1,value)})),update:vi.fn(async(_id,_version,value)=>({plan:plan(2,value)})),revisions:vi.fn(async()=>({revisions:[{...plan(2),revision_number:2,revision_id:'revision-2'},{...plan(),revision_number:1,revision_id:'revision-1'}]})),...overrides}; }
async function mountView(api=apiFixture(),availabilityApi=null,extraProvide={}) { const m=await import('./PlansView.vue').catch(()=>null);expect(m).not.toBeNull();const session=reactive({status:'authenticated',user:{user_id:'a',username:'Alice'},csrfToken:'csrf-a',refresh:vi.fn()});const wrapper=mount(m.default,{global:{stubs:{RouterLink:{template:"<a><slot /></a>"}},provide:{planApi:api,sessionStore:session,availabilitySimulationApi:availabilityApi,...extraProvide}}});await flushPromises();return {wrapper,api,session,availabilityApi}; }
async function newDraft(wrapper) {await wrapper.get('[data-testid="new-plan"]').trigger('click');await flushPromises();await wrapper.get('[name="venue_preference"]').setValue('周末人工意向');await wrapper.get('[name="court_preferences"]').setValue('6号场\n5号场');await wrapper.get('[name="target_date"]').setValue('2026-10-20');await flushPromises();}
async function edit(wrapper) { await wrapper.get('[data-testid="edit-plan"]').trigger('click');await flushPromises(); }
function gridFixture(){return {options:vi.fn(async()=>({enabled:false,grid_preview_enabled:true,grid_scenarios:[{id:'partially_occupied',name:'部分占用'}]})),gridPreview:vi.fn(async(payload)=>({grid_version:'venue-time-grid-v2',simulation:true,source:{source:`synthetic-v1:${payload.scenario}`,simulation:true,data_state:'synthetic',trust_state:'synthetic'},scenario:payload.scenario,notice:'合成预览',target_date:payload.target_date,timezone_name:'Asia/Shanghai',venue:{display_name:payload.venue_preference,verification:'unverified_manual'},atom_minutes:30,duration_minutes:payload.duration_minutes,courts:payload.court_preferences.map(display_name=>({display_name,verification:'unverified_manual'})),rows:Array.from({length:12},(_,row)=>({start_time:`${String(17+Math.floor(row/2)).padStart(2,'0')}:${row%2?'30':'00'}`,end_time:`${String(17+Math.floor(row/2)+(row%2)).padStart(2,'0')}:${row%2?'00':'30'}`,cells:payload.court_preferences.map(()=>({state:row<8?'selectable':'unknown',selectable:row<8,reason_code:row<8?'synthetic_selectable':'synthetic_unknown',category_label:null}))})),can_query_upstream:false,can_book:false,can_pay:false,can_create_job:false})),match:vi.fn()};}
async function chooseGridBlock(wrapper){await wrapper.get('[data-testid="grid-load"]').trigger('click');await flushPromises();for(const row of [0,1,2,3])await wrapper.get(`[data-testid="grid-cell-${row}-0"]`).trigger('click');await wrapper.get('[data-testid="grid-add-backup-1"]').trigger('click');await flushPromises();}

describe('manual plans page',()=>{
 it('defaults to third-day query and exposes four ordered sections without the redundant header',async()=>{
  const {wrapper,api}=await mountView();
  expect(wrapper.findAll('[role="tab"]').map(tab=>tab.text().replace(/\s+/g,''))).toEqual(['查询场地','选择预约','Agent预约','当前计划1']);
  expect(wrapper.get('#plan-panel-query').isVisible()).toBe(true);
  expect(wrapper.get('#plan-panel-manual').isVisible()).toBe(false);
  expect(wrapper.find('.plans-heading').exists()).toBe(false);
  expect(wrapper.get('#plan-panel-query [data-testid="browse-date-2"]').attributes('aria-pressed')).toBe('true');
  await wrapper.get('#plan-panel-query [data-testid="browse-date-0"]').trigger('click');
  expect(api.create).not.toHaveBeenCalled();
  await wrapper.get('[data-testid="plan-tab-manual"]').trigger('click');await flushPromises();
  expect(wrapper.get('[name="target_date"]').element.value).toBe(windowState.default_target_date);
  await wrapper.get('#plan-panel-manual [data-testid="browse-date-1"]').trigger('click');
  expect(wrapper.get('[name="target_date"]').element.value).toBe(windowState.queryable_target_dates[1]);
 });
 it('retains the manual draft and agent text while switching between all four sections',async()=>{
  const {wrapper}=await mountView(apiFixture(),null,{planningProposalApi:{generate:vi.fn()}});
  await newDraft(wrapper);
  await wrapper.get('[data-testid="plan-tab-agent"]').trigger('click');
  await wrapper.get('[data-testid="proposal-message"]').setValue('保留我正在补充的预约需求');
  await wrapper.get('[data-testid="plan-tab-current"]').trigger('click');
  expect(wrapper.get('#plan-panel-current').isVisible()).toBe(true);
  await wrapper.get('[data-testid="plan-tab-manual"]').trigger('click');
  expect(wrapper.get('[name="venue_preference"]').element.value).toBe('周末人工意向');
  expect(wrapper.get('[name="target_date"]').element.value).toBe('2026-10-20');
  await wrapper.get('[data-testid="plan-tab-agent"]').trigger('click');
  expect(wrapper.get('[data-testid="proposal-message"]').element.value).toBe('保留我正在补充的预约需求');
 });
 it('keeps secondary controls collapsed and makes fallback permissions visible in a compact summary',async()=>{
  const {wrapper}=await mountView();await edit(wrapper);
  expect(wrapper.get('.editor-disclosure').attributes('open')).toBeUndefined();
  expect(wrapper.get('.editor-disclosure>summary').text()).toContain('不换场 · 不浮动');
  await wrapper.get('[name="allow_any_court"]').setValue(true);
  expect(wrapper.get('.editor-disclosure>summary').text()).toContain('可换场');
  expect(wrapper.get('[data-testid="add-time"]').attributes('aria-label')).toBe('添加开始时间');
  expect(wrapper.get('.plan-reference-details').attributes('open')).toBeUndefined();
 });
 it('reviews an independent preference grid and saves semantic values without any observation expiry',async()=>{
  const {wrapper,api}=await mountView();await newDraft(wrapper);
  await wrapper.get('[data-testid="intent-cell-4-1"]').trigger('click');await wrapper.get('[data-testid="intent-cell-5-1"]').trigger('click');
  await wrapper.get('[data-testid="intent-cell-4-0"]').trigger('click');
  await wrapper.get('[aria-label="将意向场地 2 提前"]').trigger('click');
  await wrapper.get('[data-testid="apply-intent-selection"]').trigger('click');
  expect(wrapper.find('[data-testid="grid-apply-confirmation"]').exists()).toBe(true);expect(api.create).not.toHaveBeenCalled();
  await wrapper.get('[data-testid="confirm-grid-selection"]').trigger('click');
  await wrapper.get('form').trigger('submit');await flushPromises();
  expect(api.create.mock.calls[0][0]).toMatchObject({target_date:'2026-10-20',court_preferences:['6号场','5号场'],preferred_start_times:['18:00'],duration_minutes:60});
  expect(JSON.stringify(api.create.mock.calls[0][0])).not.toMatch(/observation_|coordinates|intent_timezone/);
 });
 it('supports arrow-key navigation and exposes tab selection to assistive technology',async()=>{
  const {wrapper}=await mountView();
  await wrapper.get('[data-testid="plan-tab-manual"]').trigger('keydown',{key:'ArrowRight'});
  expect(wrapper.get('[data-testid="plan-tab-agent"]').attributes('aria-selected')).toBe('true');
  await wrapper.get('[data-testid="plan-tab-agent"]').trigger('keydown',{key:'End'});
  expect(wrapper.get('[data-testid="plan-tab-current"]').attributes('aria-selected')).toBe('true');
 });
 it('keeps the query date independent from unsaved plan dates and ignores query apply events',async()=>{
  const liveApi={options:vi.fn(async()=>({enabled:true})),categories:vi.fn(async()=>({data_state:'live_observed_unverified',source:'official_read_only',options:[{reference:'opaque-test-ref',label:'羽毛球',physical_venue_verified:false}]})),grid:vi.fn(async()=>null)};
  const credentialApi={list:vi.fn(async()=>({credentials:[{credential_id:'owned-credential',label:'Test',enabled:true,account_binding_state:'confirmed',requires_revalidation:false,last_confirmed_validation_state:'confirmed_valid',expiry_state:'expiry_ok'}]}))};
  const {wrapper,api}=await mountView(apiFixture(),null,{liveAvailabilityApi:liveApi,credentialApi});
  await newDraft(wrapper);await new Promise(resolve=>setTimeout(resolve,20));await flushPromises();
  expect(wrapper.get('[data-testid="live-target-date"]').text()).toBe(windowState.default_target_date);
  await wrapper.get('[name="target_date"]').setValue('2026-10-21');await flushPromises();
  expect(wrapper.get('[data-testid="live-target-date"]').text()).toBe(windowState.default_target_date);
  expect(api.create).not.toHaveBeenCalled();
 });
 it('loads owned plans and clearly labels unverified intent and far-date policy',async()=>{const {wrapper}=await mountView();expect(wrapper.text()).toContain('人工意向场馆');expect(wrapper.text()).toContain('未绑定');await edit(wrapper);expect(wrapper.text()).toContain('当前不可查询');expect(wrapper.text()).toContain('07:30');expect(wrapper.text()).toContain('估计');expect(wrapper.text()).not.toContain('立即预约');});
 it('explains why no physical venue catalog or real availability is available',async()=>{const {wrapper}=await mountView();expect(wrapper.get('[data-testid="venue-catalog-status"]').text()).toContain('可信场馆目录尚未配置');expect(wrapper.text()).toContain('目录版本：未配置');expect(wrapper.text()).toContain('协议证据部分确认');expect(wrapper.text()).toContain('场馆显示名到查询范围');expect(wrapper.text()).toContain('不能据此绑定场馆');expect(wrapper.text()).toContain('属于所选场馆');expect(wrapper.find('[data-testid="bind-venue"]').exists()).toBe(false);});
 it('applies a confirmed contiguous grid block as ordered semantic preferences before saving',async()=>{const gridApi=gridFixture();const {wrapper,api}=await mountView(apiFixture({list:vi.fn(async()=>({plans:[]}))}),gridApi);await newDraft(wrapper);await chooseGridBlock(wrapper);expect(gridApi.gridPreview).toHaveBeenCalledWith({target_date:'2026-10-20',duration_minutes:120,venue_preference:'周末人工意向',court_preferences:['6号场','5号场'],scenario:'partially_occupied'});expect(wrapper.get('[data-testid="grid-apply"]').element.disabled).toBe(false);await wrapper.get('[data-testid="grid-apply"]').trigger('click');await flushPromises();expect(api.create).not.toHaveBeenCalled();expect(wrapper.get('[name="start_time_0"]').element.value).toBe('18:00');expect(wrapper.get('[data-testid="confirm-grid-selection"]').exists()).toBe(true);await wrapper.get('[data-testid="confirm-grid-selection"]').trigger('click');await flushPromises();expect(wrapper.get('[name="start_time_0"]').element.value).toBe('17:00');expect(wrapper.get('[name="court_preferences"]').element.value).toBe('6号场\n5号场');await wrapper.get('form').trigger('submit');await flushPromises();expect(api.create).toHaveBeenCalledOnce();expect(api.create.mock.calls[0][0]).toMatchObject({target_date:'2026-10-20',preferred_start_times:['17:00'],duration_minutes:120,court_preferences:['6号场','5号场'],fallback_policy:{allow_any_court_in_venue:false,allow_time_shift:false,allowed_start_time_range:null}});expect(api.create.mock.calls[0][0]).not.toHaveProperty('coordinatesList');});
 it('keeps applied grid intent in the form after a 409 conflict',async()=>{const gridApi=gridFixture();const api=apiFixture({update:vi.fn(async()=>{throw {status:409,code:'plan_version_conflict'};})});const {wrapper}=await mountView(api,gridApi);await edit(wrapper);await chooseGridBlock(wrapper);await wrapper.get('[data-testid="grid-apply"]').trigger('click');await flushPromises();await wrapper.get('[data-testid="confirm-grid-selection"]').trigger('click');await wrapper.get('form').trigger('submit');await flushPromises();expect(wrapper.text()).toContain('版本冲突');expect(wrapper.get('[name="start_time_0"]').element.value).toBe('17:00');expect(wrapper.get('[name="court_preferences"]').element.value).toBe('6号场优先\n5号场备选');});
 it('creates a semantic draft with time priority and exact price',async()=>{const {wrapper,api}=await mountView(apiFixture({list:vi.fn(async()=>({plans:[]}))}));expect(wrapper.text()).toContain('还没有预约计划');await newDraft(wrapper);await wrapper.get('[data-testid="add-time"]').trigger('click');await wrapper.get('[name="start_time_1"]').setValue('20:00');await wrapper.get('[data-testid="time-up-1"]').trigger('click');await wrapper.get('[name="price_ceiling"]').setValue('0.29');await wrapper.get('form').trigger('submit');await flushPromises();expect(api.create.mock.calls[0][0]).toMatchObject({venue_preference:'周末人工意向',court_preferences:['6号场','5号场'],preferred_start_times:['20:00','18:00'],price_ceiling_minor:29});expect(wrapper.text()).toContain('已保存');expect(wrapper.text()).toContain('周末人工意向');});
 it('edits using base_version and opens immutable history',async()=>{const {wrapper,api}=await mountView();await edit(wrapper);await wrapper.get('[name="venue_preference"]').setValue('修改意向');await wrapper.get('form').trigger('submit');await flushPromises();expect(api.update.mock.calls[0].slice(0,2)).toEqual(['synthetic-plan',1]);expect(wrapper.text()).toContain('版本 2');await wrapper.get('[data-testid="history-plan"]').trigger('click');await flushPromises();expect(wrapper.text()).toContain('版本历史');expect(wrapper.findAll('details').length).toBeGreaterThanOrEqual(2);expect(wrapper.text()).toContain('人工意向场馆');});
 it('keeps draft on 409, previews latest separately and replaces only on explicit adoption',async()=>{const {wrapper}=await mountView(apiFixture({update:vi.fn(async()=>{throw {status:409,code:'plan_version_conflict'};})}));await edit(wrapper);await wrapper.get('[name="venue_preference"]').setValue('我的未保存意向');await wrapper.get('form').trigger('submit');await flushPromises();expect(wrapper.text()).toContain('版本冲突');expect(wrapper.get('[name="venue_preference"]').element.value).toBe('我的未保存意向');await wrapper.get('[data-testid="view-latest"]').trigger('click');await flushPromises();expect(wrapper.text()).toContain('另一个窗口保存');expect(wrapper.get('[name="venue_preference"]').element.value).toBe('我的未保存意向');await wrapper.get('[data-testid="adopt-latest"]').trigger('click');await flushPromises();expect(wrapper.get('[name="venue_preference"]').element.value).toBe('另一个窗口保存');});
 it('does not report load failure as an empty list and retries successfully',async()=>{let bad=true;const {wrapper}=await mountView(apiFixture({list:vi.fn(async()=>{if(bad)throw {kind:'network'};return {plans:[]};})}));expect(wrapper.text()).toContain('计划读取失败');expect(wrapper.text()).not.toContain('还没有预约计划');bad=false;await wrapper.get('[data-testid="refresh-plans"]').trigger('click');await flushPromises();expect(wrapper.text()).toContain('还没有预约计划');});
 it('preserves form after network save failure and shows uncertain outcome',async()=>{const {wrapper}=await mountView(apiFixture({update:vi.fn(async()=>{throw {kind:'network'};})}));await edit(wrapper);await wrapper.get('[name="venue_preference"]').setValue('保留文本');await wrapper.get('form').trigger('submit');await flushPromises();expect(wrapper.get('[name="venue_preference"]').element.value).toBe('保留文本');expect(wrapper.text()).toContain('保存结果尚未确认');});
 it('shows field errors without discarding input',async()=>{const {wrapper}=await mountView(apiFixture({update:vi.fn(async()=>{throw {code:'invalid_plan',status:400,fields:{venue_preference:'场馆文本无效'}};})}));await edit(wrapper);await wrapper.get('form').trigger('submit');await flushPromises();expect(wrapper.text()).toContain('场馆文本无效');expect(wrapper.get('[name="venue_preference"]').attributes('aria-invalid')).toBe('true');});
 it('blocks duplicates while saving and disables editing actions',async()=>{let resolve;const {wrapper,api}=await mountView(apiFixture({update:vi.fn(()=>new Promise(r=>{resolve=r;}))}));await edit(wrapper);await wrapper.get('form').trigger('submit');await wrapper.get('form').trigger('submit');expect(api.update).toHaveBeenCalledOnce();expect(wrapper.get('[data-testid="new-plan"]').element.disabled).toBe(true);resolve({plan:plan(2)});await flushPromises();});
 it('preserves the same user draft after session invalidation and ignores late save data',async()=>{let resolve;const {wrapper,session}=await mountView(apiFixture({update:vi.fn(()=>new Promise(r=>{resolve=r;}))}));await edit(wrapper);await wrapper.get('[name="venue_preference"]').setValue('我的未保存意向');await wrapper.get('form').trigger('submit');session.invalidatedUserId='a';session.invalidationEpoch=(session.invalidationEpoch||0)+1;session.user=null;session.status='unauthenticated';await flushPromises();expect(wrapper.find('form').exists()).toBe(false);session.user={user_id:'a',username:'Alice'};session.csrfToken='csrf-new';session.status='authenticated';await flushPromises();resolve({plan:plan(2,{venue_preference:'迟到结果'})});await flushPromises();expect(wrapper.find('form').exists()).toBe(true);expect(wrapper.get('[name="venue_preference"]').element.value).toBe('我的未保存意向');expect(wrapper.text()).not.toContain('迟到结果');expect(wrapper.text()).toContain('未保存表单已恢复');});
 it('does not restore a suspended draft over a plan the user opens while session data reloads',async()=>{
   let finishOptions;
   const {wrapper,api,session}=await mountView();
   await edit(wrapper);
   await wrapper.get('[name="venue_preference"]').setValue('恢复中的旧草稿');
   session.invalidatedUserId='a';session.invalidationEpoch=(session.invalidationEpoch||0)+1;session.user=null;session.status='unauthenticated';
   await flushPromises();
   api.options=vi.fn(()=>new Promise(resolve=>{finishOptions=resolve;}));
   session.user={user_id:'a',username:'Alice'};session.csrfToken='csrf-new';session.status='authenticated';
   await flushPromises();
   expect(wrapper.find('[data-testid="edit-plan"]').exists()).toBe(true);
   await wrapper.get('[data-testid="edit-plan"]').trigger('click');
   await wrapper.get('[name="venue_preference"]').setValue('用户新选择的计划');
   finishOptions({catalog_status:'not_configured',catalog_version:null,source_state:'protocol_evidence_partial',venues:[],capabilities:{display:false,plan_binding:false,historical_availability:false,live_availability:false},context:clone(context)});
   await flushPromises();
   expect(wrapper.get('[name="venue_preference"]').element.value).toBe('用户新选择的计划');
   api.options=vi.fn(async()=>({catalog_status:'not_configured',catalog_version:null,source_state:'protocol_evidence_partial',venues:[],capabilities:{display:false,plan_binding:false,historical_availability:false,live_availability:false},context:clone(context)}));
   session.invalidatedUserId='a';session.invalidationEpoch+=1;session.user=null;session.status='unauthenticated';
   await flushPromises();
   session.invalidatedUserId=null;session.user={user_id:'a',username:'Alice'};session.csrfToken='csrf-newer';session.status='authenticated';
   await flushPromises();
   expect(wrapper.get('[name="venue_preference"]').element.value).toBe('用户新选择的计划');
 });
 it('does not restore an invalidated user draft into another account',async()=>{const {wrapper,session}=await mountView(apiFixture({list:vi.fn(async()=>({plans:[]}))}));await wrapper.get('[data-testid="new-plan"]').trigger('click');await wrapper.get('[name="venue_preference"]').setValue('仅属于 Alice 的草稿');session.invalidatedUserId='a';session.invalidationEpoch=(session.invalidationEpoch||0)+1;session.user=null;session.status='unauthenticated';await flushPromises();session.invalidatedUserId=null;session.user={user_id:'b',username:'Bob'};session.csrfToken='csrf-b';session.status='authenticated';await flushPromises();expect(wrapper.text()).not.toContain('仅属于 Alice 的草稿');expect(wrapper.find('form').exists()).toBe(false);});
 it('clears owned data on account switch and ignores the old list response',async()=>{let resolve;let calls=0;const {wrapper,session}=await mountView(apiFixture({list:vi.fn(()=>++calls===1?new Promise(r=>{resolve=r;}):Promise.resolve({plans:[]}))}));session.user={user_id:'b',username:'Bob'};await flushPromises();resolve({plans:[plan()]});await flushPromises();expect(wrapper.text()).not.toContain('人工意向场馆');expect(wrapper.text()).toContain('还没有预约计划');});
 it('clears owned data when the same user receives a new session token',async()=>{const {wrapper,session}=await mountView();await edit(wrapper);session.csrfToken='csrf-rotated';await flushPromises();expect(wrapper.find('form').exists()).toBe(false);expect(wrapper.text()).not.toContain('编辑预约意向');});
 it('uses stored currency/timezone for edits and does not accept absent currency price',async()=>{const {wrapper}=await mountView(apiFixture({options:vi.fn(async()=>({catalog_status:'not_configured',venues:[],context:{...context,currency_code:null,currency_minor_unit_exponent:null,timezone_name:'UTC'}}))}));await edit(wrapper);expect(wrapper.get('[name="price_ceiling"]').element.value).toBe('12.34');expect(wrapper.text()).toContain('CNY');expect(wrapper.text()).toContain('Asia/Shanghai');await newDraft(wrapper);expect(wrapper.find('[name="price_ceiling"]').exists()).toBe(false);expect(wrapper.find('[name="price_ceiling"]').exists()).toBe(false);});
 it('settles a pending list refresh after a rejected save',async()=>{
   let finishRefresh;let calls=0;
   const {wrapper}=await mountView(apiFixture({
     list:vi.fn(()=>++calls===1?Promise.resolve({plans:[plan()]}):new Promise(resolve=>{finishRefresh=resolve;})),
     update:vi.fn(async()=>{throw {status:400,fields:{venue_preference:'请检查场馆文本'}};}),
   }));
   await edit(wrapper);
   await wrapper.get('[data-testid="refresh-plans"]').trigger('click');
   await wrapper.get('form').trigger('submit');
   await flushPromises();
   finishRefresh({plans:[plan()]});await flushPromises();
   expect(wrapper.get('[data-testid="refresh-plans"]').element.disabled).toBe(false);
   expect(wrapper.text()).not.toContain('正在读取计划');
 });

});
