import { flushPromises, mount, enableAutoUnmount } from '@vue/test-utils';
import { reactive } from 'vue';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { intent, plan } from './testFixtures.js';

enableAutoUnmount(afterEach);
const proposal={intent:{...intent,venue_preference:'AI场馆意向'},context:{},kind:'unbound_draft',plan_id:null,base_version:null,before_intent:null,changes:[{field:'venue_preference',before:'',after:'AI场馆意向'}],booking_window:{can_book:false},provider:{name:'Test provider',model:'test-model'},can_book:false,can_pay:false,can_create_job:false,can_query_upstream:false};
function fixture({plans=[],proposalResult={status:'ready',questions:[],proposal},planOverrides={}}={}){
 const saved=plan(2,{venue_preference:'AI场馆意向'});
 const planApi={get:vi.fn(async()=>({plan:plan(3,{venue_preference:'latest venue'})})),create:vi.fn(async()=>({plan:saved})),update:vi.fn(async()=>({plan:saved})),...planOverrides};
 const proposalApi={generate:vi.fn(async()=>structuredClone(proposalResult))};
 const session=reactive({status:'authenticated',user:{user_id:'owner'},csrfToken:'csrf-a'});
 return {planApi,proposalApi,session,plans};
}
async function mountAssistant(config=fixture()) {const {default:component}=await import('./ProposalAssistant.vue');const wrapper=mount(component,{props:{plans:config.plans,planApi:config.planApi,proposalApi:config.proposalApi,session:config.session},global:{stubs:{RouterLink:{template:'<a><slot /></a>'}}}});await flushPromises();return {wrapper,...config};}

describe('proposal assistant',()=>{
 it('previews a ready result and waits for explicit confirmation before saving',async()=>{
  const {wrapper,planApi,proposalApi}=await mountAssistant();await wrapper.get('[data-testid="proposal-message"]').setValue('新建周末意向');await wrapper.get('[data-testid="generate-proposal"]').trigger('click');await flushPromises();
  expect(proposalApi.generate).toHaveBeenCalledWith('新建周末意向',null,null);expect(wrapper.text()).toContain('建议预览');expect(wrapper.text()).toContain('AI场馆意向');expect(wrapper.text()).toContain('预约、付款、创建任务和上游查询均不可用');expect(planApi.create).not.toHaveBeenCalled();
  await wrapper.get('[data-testid="confirm-save-proposal"]').trigger('click');await flushPromises();expect(planApi.create).toHaveBeenCalledWith(proposal.intent);expect(wrapper.text()).toContain('预约意向已保存');
 });
 it('keeps the save notice when the parent list refreshes to the version just saved',async()=>{
  const config=fixture({plans:[plan(1)]});const {wrapper}=await mountAssistant(config);await wrapper.get('[data-testid="proposal-message"]').setValue('更新现有意向');await wrapper.get('[data-testid="proposal-target"]').setValue('synthetic-plan');await wrapper.get('[data-testid="generate-proposal"]').trigger('click');await flushPromises();await wrapper.get('[data-testid="confirm-save-proposal"]').trigger('click');await flushPromises();expect(wrapper.text()).toContain('预约意向已保存 · 版本 2');
  await wrapper.setProps({plans:[plan(2)]});await flushPromises();expect(wrapper.text()).toContain('预约意向已保存 · 版本 2');
  await wrapper.setProps({plans:[plan(3)]});await flushPromises();expect(wrapper.text()).not.toContain('预约意向已保存 · 版本 2');
 });
 it('loads the latest owned plan before proposing an edit and saves with its base version',async()=>{
  const config=fixture({plans:[plan(2)]});const {wrapper,planApi,proposalApi}=await mountAssistant(config);await wrapper.get('[data-testid="proposal-message"]').setValue('改一下场馆');await wrapper.get('[data-testid="proposal-target"]').setValue('synthetic-plan');await wrapper.get('[data-testid="generate-proposal"]').trigger('click');await flushPromises();expect(planApi.get).toHaveBeenCalledWith('synthetic-plan');expect(proposalApi.generate).toHaveBeenCalledWith('改一下场馆','synthetic-plan',3);
  await wrapper.get('[data-testid="confirm-save-proposal"]').trigger('click');await flushPromises();expect(planApi.update).toHaveBeenCalledWith('synthetic-plan',3,proposal.intent);
 });
 it('renders follow-up questions and keeps the original message when cancelled',async()=>{
  const {wrapper,proposalApi}=await mountAssistant(fixture({proposalResult:{status:'needs_input',questions:['哪一天？'],proposal:null}}));await wrapper.get('[data-testid="proposal-message"]').setValue('周末晚上');await wrapper.get('[data-testid="generate-proposal"]').trigger('click');await flushPromises();expect(wrapper.text()).toContain('哪一天？');await wrapper.get('[data-testid="cancel-proposal"]').trigger('click');expect(wrapper.get('[data-testid="proposal-message"]').element.value).toBe('周末晚上');expect(proposalApi.generate).toHaveBeenCalledOnce();
 });
 it('shows an unsupported explanation returned by the assistant',async()=>{
  const {wrapper}=await mountAssistant(fixture({proposalResult:{status:'unsupported',questions:['无法执行预约或付款。'],proposal:null}}));await wrapper.get('[data-testid="proposal-message"]').setValue('帮我直接预订');await wrapper.get('[data-testid="generate-proposal"]').trigger('click');await flushPromises();expect(wrapper.text()).toContain('无法执行预约或付款。');expect(wrapper.find('[data-testid="confirm-save-proposal"]').exists()).toBe(false);
 });
 it('formats field diffs for people instead of showing internal objects and minor units',async()=>{
  const detailed={...proposal,context:{currency_code:'CNY',currency_minor_unit_exponent:2},changes:[
   {field:'target_date',before:'2026-10-20',after:'2026-10-24'},
   {field:'preferred_start_times',before:['18:00','19:00'],after:['20:00']},
   {field:'fallback_policy',before:{allow_any_court_in_venue:false,allow_time_shift:false,allowed_start_time_range:null},after:{allow_any_court_in_venue:true,allow_time_shift:true,allowed_start_time_range:{start:'18:00',end:'21:00'}}},
   {field:'price_ceiling_minor',before:1234,after:5678},
  ]};
  const {wrapper}=await mountAssistant(fixture({proposalResult:{status:'ready',questions:[],proposal:detailed}}));await wrapper.get('[data-testid="proposal-message"]').setValue('改意向');await wrapper.get('[data-testid="generate-proposal"]').trigger('click');await flushPromises();expect(wrapper.text()).toContain('2026年10月20日');expect(wrapper.text()).toContain('2026年10月24日');expect(wrapper.text()).toContain('18:00 → 19:00（按优先顺序）');expect(wrapper.text()).toContain('允许开始时间在 18:00 至 21:00 浮动');expect(wrapper.text()).toContain('12.34 CNY');expect(wrapper.text()).not.toContain('[object Object]');expect(wrapper.text()).not.toContain('1234');
 });
 it('keeps description on model failure and disables a stale preview after input changes',async()=>{
  const failed=fixture();failed.proposalApi.generate=vi.fn(async()=>{throw {code:'provider_unavailable'};});
  const first=await mountAssistant(failed);await first.wrapper.get('[data-testid="proposal-message"]').setValue('原始描述保留');await first.wrapper.get('[data-testid="generate-proposal"]').trigger('click');await flushPromises();expect(first.wrapper.text()).toContain('生成建议失败');expect(first.wrapper.get('[data-testid="proposal-message"]').element.value).toBe('原始描述保留');
  const second=await mountAssistant();await second.wrapper.get('[data-testid="proposal-message"]').setValue('初始建议');await second.wrapper.get('[data-testid="generate-proposal"]').trigger('click');await flushPromises();await second.wrapper.get('[data-testid="proposal-message"]').setValue('已修改描述');expect(second.wrapper.get('[data-testid="confirm-save-proposal"]').element.disabled).toBe(true);expect(second.planApi.create).not.toHaveBeenCalled();
 });
 it('preserves message and proposal on 409, then explicitly reads latest and regenerates',async()=>{
  const planApi={get:vi.fn(async()=>({plan:plan(4,{venue_preference:'最新人工偏好'})})),create:vi.fn(),update:vi.fn(async()=>{throw {status:409,code:'plan_version_conflict'};})};
  const proposalApi={generate:vi.fn(async()=>structuredClone({...{status:'ready',questions:[]},proposal:{...proposal,base_version:3,plan_id:'synthetic-plan'}}))};
  const config=fixture({plans:[plan(2)],planOverrides:planApi});config.proposalApi=proposalApi;
  const {wrapper}=await mountAssistant(config);await wrapper.get('[data-testid="proposal-message"]').setValue('保留我的描述');await wrapper.get('[data-testid="proposal-target"]').setValue('synthetic-plan');await wrapper.get('[data-testid="generate-proposal"]').trigger('click');await flushPromises();await wrapper.get('[data-testid="confirm-save-proposal"]').trigger('click');await flushPromises();
  expect(wrapper.get('[data-testid="proposal-message"]').element.value).toBe('保留我的描述');expect(wrapper.text()).toContain('建议预览');expect(wrapper.get('[data-testid="confirm-save-proposal"]').element.disabled).toBe(true);await wrapper.get('[data-testid="read-latest-regenerate"]').trigger('click');await flushPromises();expect(wrapper.text()).toContain('最新人工偏好');expect(proposalApi.generate).toHaveBeenLastCalledWith('保留我的描述','synthetic-plan',4);
 });
 it('treats a missing provider key 409 as a model-settings error, not a plan conflict',async()=>{
  const config=fixture();config.proposalApi.generate=vi.fn(async()=>{throw {status:409,code:'provider_api_key_required'};});const {wrapper}=await mountAssistant(config);await wrapper.get('[data-testid="proposal-message"]').setValue('生成意向');await wrapper.get('[data-testid="generate-proposal"]').trigger('click');await flushPromises();expect(wrapper.text()).toContain('当前模型缺少 API Key');expect(wrapper.text()).toContain('前往设置AI模型');expect(wrapper.text()).not.toContain('计划版本已变化');expect(wrapper.find('[data-testid="read-latest-regenerate"]').exists()).toBe(false);
 });
 it('blocks ambiguous retries until a list check and explicit acknowledgment',async()=>{
  const planApi={...fixture().planApi,list:vi.fn(async()=>({plans:[plan(1)]})),create:vi.fn().mockRejectedValueOnce({kind:'network',status:0}).mockResolvedValueOnce({plan:plan(2)})};
  const config=fixture({planOverrides:planApi});const {wrapper}=await mountAssistant(config);await wrapper.get('[data-testid="proposal-message"]').setValue('新建意向');await wrapper.get('[data-testid="generate-proposal"]').trigger('click');await flushPromises();await wrapper.get('[data-testid="confirm-save-proposal"]').trigger('click');await flushPromises();
  expect(wrapper.text()).toContain('保存结果暂时无法确认');expect(wrapper.get('[data-testid="confirm-save-proposal"]').element.disabled).toBe(true);expect(planApi.create).toHaveBeenCalledOnce();
  await wrapper.get('[data-testid="verify-ambiguous-save"]').trigger('click');await flushPromises();expect(wrapper.text()).toContain('已读取计划列表，共 1 个预约计划');expect(wrapper.get('[data-testid="acknowledge-save-check"]').element.disabled).toBe(false);
  await wrapper.get('[data-testid="acknowledge-save-check"]').trigger('click');expect(wrapper.get('[data-testid="confirm-save-proposal"]').element.disabled).toBe(false);expect(planApi.create).toHaveBeenCalledOnce();
  await wrapper.get('[data-testid="confirm-save-proposal"]').trigger('click');await flushPromises();expect(planApi.create).toHaveBeenCalledTimes(2);expect(wrapper.text()).toContain('预约意向已保存');
 });
 it('ignores proposal results returned after the Session or CSRF token changes',async()=>{
  let resolve;const config=fixture();config.proposalApi.generate=vi.fn(()=>new Promise(r=>{resolve=r;}));const {wrapper,session}=await mountAssistant(config);
  await wrapper.get('[data-testid="proposal-message"]').setValue('我的文本');await wrapper.get('[data-testid="generate-proposal"]').trigger('click');session.csrfToken='csrf-b';await flushPromises();resolve({status:'ready',questions:[],proposal});await flushPromises();expect(wrapper.find('[aria-label="AI建议预览"]').exists()).toBe(false);expect(wrapper.get('[data-testid="proposal-message"]').element.value).toBe('我的文本');
 });
 it('clears the natural-language prompt and plan target when the account changes',async()=>{
  const {wrapper,session}=await mountAssistant(fixture({plans:[plan()]}));await wrapper.get('[data-testid="proposal-message"]').setValue('用户A的私有预约安排');await wrapper.get('[data-testid="proposal-target"]').setValue('synthetic-plan');session.user={user_id:'user-b'};await flushPromises();expect(wrapper.get('[data-testid="proposal-message"]').element.value).toBe('');expect(wrapper.get('[data-testid="proposal-target"]').element.value).toBe('');
 });
 it('shows provider setup guidance when a missing provider is returned as a 409',async()=>{
  const config=fixture();config.proposalApi.generate=vi.fn(async()=>{throw {status:409,code:'provider_not_configured'};});const {wrapper}=await mountAssistant(config);await wrapper.get('[data-testid="proposal-message"]').setValue('新建预约意向');await wrapper.get('[data-testid="generate-proposal"]').trigger('click');await flushPromises();expect(wrapper.text()).toContain('尚未配置 AI 模型');expect(wrapper.text()).not.toContain('计划版本已变化');
 });
});
