import { flushPromises, mount, enableAutoUnmount } from '@vue/test-utils';
import { reactive } from 'vue';
import { afterEach, describe, expect, it, vi } from 'vitest';

enableAutoUnmount(afterEach);

const entry=(court,start,end,minutes=120)=>({court_preference:court,start_time:start,end_time:end,duration_minutes:minutes,scope_label:'羽毛球'});
const ENTRIES=[entry('1号场','14:00','16:00'),entry('4号场','14:00','16:00'),entry('1号场','18:00','20:00'),entry('4号场','18:00','20:00')];
const proposal=(over={})=>({kind:'manual_queue_draft',target_date:'2026-10-20',target_label:'10月20日 周二',entries:ENTRIES,entry_count:4,base_version:0,existing_count:0,replaces_existing:false,
 schedule:{state:'scheduled',text:'10月18日 周日 07:30 开票时自动执行。'},execution_note:'执行时从上往下依次尝试，抢到第一个就停，所以顺序就是优先级。',warnings:[],review:{state:'reviewed',attempts:1},
 provider:{name:'Test provider',model:'test-model'},can_book:false,can_pay:false,can_create_job:false,can_query_upstream:false,...over});
const slotList=()=>[
 {field:'booking_mode',status:'proposed',display:'只抢2小时',active:true},
 {field:'target_date',status:'proposed',display:'10月20日 周二',active:true},
 {field:'windows_2h',status:'empty',display:'',active:true},
 {field:'overlap_2h',status:'verified',display:'',active:false},
 {field:'courts_2h',status:'empty',display:'',active:true},
 {field:'windows_1h',status:'verified',display:'',active:false},
 {field:'overlap_1h',status:'verified',display:'',active:false},
 {field:'courts_1h',status:'verified',display:'',active:false},
];
const strip=()=>[{id:'mode',label:'队列类型',state:'done',display:'只抢2小时'},{id:'date',label:'日期',state:'done',display:'10月20日 周二'},{id:'2h',label:'2小时',state:'current',display:'正在确认'},{id:'1h',label:'1小时',state:'off',display:'本次不选'}];
const conversation=(over={})=>({phase:'collecting',asking:'windows_2h',heading:'2小时时段',reason:'missing',turns_used:0,turns_max:20,attempts:{},slots:slotList(),strip:strip(),escalation:null,notices:[],...over});
const ready=(over={},prop={})=>({status:'ready',questions:[],proposal:proposal(prop),conversation:conversation({phase:'ready',asking:null,heading:null,...over})});
const ask=(text,over={})=>({status:'needs_input',questions:[text],proposal:null,conversation:conversation(over)});

function fixture({result=ready(),credentialId='credential-a',scopeLabel='羽毛球',saveQueue,queue}={}){
 const planApi={saveQueue:saveQueue||vi.fn(async()=>({queue:{plan_id:'q',version:1,candidates:[]}})),queue:queue||vi.fn(async()=>({queue:null}))};
 const proposalApi={generate:vi.fn(async()=>structuredClone(result)),restore:vi.fn(async()=>({conversation:null,conversations:[]})),resume:vi.fn(async()=>({conversation:null})),close:vi.fn(async()=>({}))};
 const session=reactive({status:'authenticated',user:{user_id:'owner'},csrfToken:'csrf-a'});
 return {planApi,proposalApi,session,credentialId,scopeLabel,credentialApi:null,credentialRefreshKey:0};
}
async function mountAssistant(config=fixture()){
 const {default:component}=await import('./ProposalAssistant.vue');
 const wrapper=mount(component,{props:{planApi:config.planApi,proposalApi:config.proposalApi,credentialApi:config.credentialApi,credentialRefreshKey:config.credentialRefreshKey,session:config.session,credentialId:config.credentialId,scopeLabel:config.scopeLabel},global:{stubs:{RouterLink:{template:'<a><slot /></a>'}}}});
 await flushPromises();return {wrapper,...config};
}
const send=async(wrapper,text)=>{await wrapper.get('[data-testid="proposal-message"]').setValue(text);await wrapper.get('[data-testid="generate-proposal"]').trigger('click');await flushPromises();};
const reply=async(wrapper,text)=>{await wrapper.get('[data-testid="proposal-answer"]').setValue(text);await wrapper.get('[data-testid="continue-proposal"]').trigger('click');await flushPromises();};
describe('queue assistant: asking',()=>{
 it('opens with duration choices and optional structured selectors',async()=>{
  const {wrapper}=await mountAssistant();
  expect(wrapper.text()).toContain('1 / A 只抢2小时');
  expect(wrapper.text()).toContain('2 / B 只抢1小时');
  expect(wrapper.text()).toContain('3 / C 两种都抢');
  expect(wrapper.text()).toContain('先选队列类型，再确认日期；2小时和1小时的时段、场地分开核对');
  expect(wrapper.find('.proposal-mode-picker').exists()).toBe(false);
  expect(wrapper.get('[data-testid="proposal-field-mode"]').exists()).toBe(true);
  expect(wrapper.get('[data-testid="proposal-field-windows-1h"]').exists()).toBe(true);
  expect(wrapper.text()).not.toContain('新建');expect(wrapper.text()).not.toContain('场馆');
 });

 it('sends the first message with the credential and the query category',async()=>{
  const {wrapper,proposalApi}=await mountAssistant(fixture({result:ask('想订哪一天？'),scopeLabel:'羽毛球'}));
  await send(wrapper,'我想订场');
  expect(proposalApi.generate).toHaveBeenCalledWith({message:'我想订场',credentialId:'credential-a',answers:[],askedFields:[],scopeLabel:'羽毛球'});
  expect(wrapper.text()).toContain('想订哪一天？');
 });

 it('shows the server workflow stages returned for the turn',async()=>{
  const workflowTrace=[
   {stage:'准备上下文',detail:'已加载3轮用户消息、2轮助手校验记录。'},
   {stage:'模型理解',detail:'已按结构化协议解释本轮意图。模型：deepseek-flash。'},
   {stage:'应用更新并校验',detail:'有效候选 4/32；当前阻塞 2小时场地。'},
   {stage:'追问',detail:'等待用户补充courts_2h。'},
  ];
  const result=ask('请问两小时时段要选哪些场地？',{asking:'courts_2h',heading:'2小时场地',workflow_trace:workflowTrace});
  const {wrapper}=await mountAssistant(fixture({result}));
  await send(wrapper,'后天 14-16');
  const trace=wrapper.findAll('.proposal-trace-list .trace-item').map(item=>item.text());
  expect(trace.some(item=>item.includes('准备上下文')&&item.includes('3轮用户消息'))).toBe(true);
  expect(trace.some(item=>item.includes('模型理解')&&item.includes('deepseek-flash'))).toBe(true);
  expect(trace.some(item=>item.includes('应用更新并校验')&&item.includes('4/32'))).toBe(true);
  expect(trace.some(item=>item.includes('追问')&&item.includes('courts_2h'))).toBe(true);
 });

 it('renders the model context answer together with the remaining question',async()=>{
  const contextualReply='日期已记录10月26日，2小时队列和14-16时段通过校验；场地还没记录。';
  const {wrapper}=await mountAssistant(fixture({result:ask('2小时选哪些场地？例如1号和4号。',{
   asking:'courts_2h',heading:'2小时场地',contextual_reply:contextualReply,
  })}));
  await send(wrapper,'我已经确认了什么？');
  expect(wrapper.get('.contextual-reply').text()).toBe(contextualReply);
  expect(wrapper.text()).toContain('2小时选哪些场地？例如1号和4号。');
 });

 it('keeps earlier contextual answers visible after the next user reply',async()=>{
  const earlierReply='日期已记录10月26日，2小时14-16通过校验；场地还没记录。';
  const laterReply='2小时场地已记录为1号场；1小时队列仍独立确认。';
  const config=fixture();
  config.proposalApi.generate=vi.fn()
   .mockResolvedValueOnce(ask('2小时选哪些场地？例如1号和4号。',{
    asking:'courts_2h',heading:'2小时场地',contextual_reply:earlierReply,
   }))
   .mockResolvedValueOnce(ask('还要排1小时吗？例如14-15。',{
    asking:'windows_1h',heading:'1小时时段',contextual_reply:laterReply,
   }));
  const {wrapper}=await mountAssistant(config);
  await send(wrapper,'10月26日只抢2小时14-16');
  await reply(wrapper,'1号场');
  const replies=wrapper.findAll('.contextual-reply').map(item=>item.text());
  expect(replies).toEqual([earlierReply,laterReply]);
  expect(wrapper.text()).toContain('1号场');
  expect(wrapper.text()).toContain('还要排1小时吗？例如14-15。');
 });

 it('fills structured choices into the chat input without sending them',async()=>{
  const {wrapper,proposalApi}=await mountAssistant();
  await wrapper.get('.proposal-field-shortcuts > summary').trigger('click');
  await wrapper.get('[data-testid="proposal-field-mode"]').setValue('只要2小时');
  await wrapper.get('[data-testid="proposal-field-windows-2h"]').setValue('14-16');
  const value=wrapper.get('[data-testid="proposal-message"]').element.value;
  expect(value).toContain('队列类型：只要2小时');expect(value).toContain('2小时时段：14-16');
  expect(proposalApi.generate).not.toHaveBeenCalled();
 });

 it('uses the duration quick choice as the first chat turn',async()=>{
  const config=fixture({result:ask('想订哪一天？',{asking:'target_date',heading:'日期'})});
  const {wrapper,proposalApi}=await mountAssistant(config);
  await wrapper.get('.mode-quick-choices button').trigger('click');
  expect(proposalApi.generate).toHaveBeenCalledWith({message:'1',credentialId:'credential-a',answers:[],askedFields:[],scopeLabel:'羽毛球'});
 });

 it('lists and resumes a prior conversation for the selected credential',async()=>{
  const saved={conversation_id:'history-conversation-12345',business_date:'2026-10-18',message:'后天想订场',answers:[],asked_fields:[],scope_label:'羽毛球',response_history:[ask('先选择队列类型。',{asking:'booking_mode',heading:'选择队列类型'})]};
  const config=fixture();
  config.proposalApi.restore=vi.fn(async()=>({conversation:null,conversations:[{conversation_id:saved.conversation_id,title:'10月20日 · 只抢2小时',preview:'确认场地',status:'closed',updated_at_utc_ms:Date.UTC(2026,9,18)}]}));
  config.proposalApi.resume=vi.fn(async()=>({conversation:saved}));
  const {wrapper,proposalApi}=await mountAssistant(config);
  expect(wrapper.text()).toContain('10月20日 · 只抢2小时');
  await wrapper.get('.conversation-history-item').trigger('click');
  expect(proposalApi.resume).toHaveBeenCalledWith(saved.conversation_id,'credential-a');
  expect(wrapper.text()).toContain('后天想订场');
  expect(wrapper.text()).not.toContain('这条对话暂时无法恢复');
 });

 it('restores a ready queue preview without reporting a false recovery error',async()=>{
  const saved={conversation_id:'ready-conversation-12345',message:'3',answers:[],asked_fields:[],scope_label:'羽毛球',response_history:[ready()]};
  const config=fixture();config.proposalApi.restore=vi.fn(async()=>({conversation:saved,conversations:[]}));
  const {wrapper}=await mountAssistant(config);
  expect(wrapper.get('[data-testid="queue-preview"]').exists()).toBe(true);
  expect(wrapper.get('[data-testid="confirm-save-proposal"]').element.disabled).toBe(false);
  expect(wrapper.text()).not.toContain('已保存的对话暂时无法恢复');
 });

 it('locks the composer until the current conversation is archived before starting a new one',async()=>{
  let finishClose;
  const config=fixture({result:{...ready(),conversation_id:'conversation-to-archive-123'}});
  config.proposalApi.close=vi.fn(()=>new Promise(resolve=>{finishClose=resolve;}));
  const {wrapper}=await mountAssistant(config);
  await send(wrapper,'我想订场');
  await wrapper.get('[data-testid="restart-conversation"]').trigger('click');
  await flushPromises();
  expect(wrapper.get('[data-testid="proposal-answer"]').element.disabled).toBe(true);
  expect(wrapper.get('[data-testid="continue-proposal"]').element.disabled).toBe(true);
  finishClose();
  await flushPromises();
  expect(wrapper.get('[data-testid="proposal-message"]').element.disabled).toBe(false);
  expect(wrapper.get('[data-testid="proposal-message"]').element.value).toBe('');
 });

 it('shows the server heading and an independent collapsed queue preview',async()=>{
  const {wrapper}=await mountAssistant(fixture({result:ask('2小时要哪个时间段？',{asking:'courts_2h',heading:'2小时场地'})}));
  await send(wrapper,'后天');
  expect(wrapper.get('.chat-bubble strong').text()).toBe('2小时场地');
  expect(wrapper.findAll('.slot-strip li')).toHaveLength(0);
  expect(wrapper.get('.queue-preview-details summary').text()).toContain('队列预览');
  expect(wrapper.text()).toContain('2小时队列');
 });

 it('echoes the field each earlier question was about so the server can count repeats',async()=>{
  const config=fixture();config.proposalApi.generate=vi.fn()
   .mockResolvedValueOnce(ask('想订哪一天？',{asking:'target_date',heading:'日期'}))
   .mockResolvedValueOnce(ask('2小时要哪个时间段？',{asking:'windows_2h'}))
   .mockResolvedValueOnce(ready());
  const {wrapper,proposalApi}=await mountAssistant(config);
  await send(wrapper,'我想订场');await reply(wrapper,'后天');await reply(wrapper,'14-16');
  expect(proposalApi.generate).toHaveBeenNthCalledWith(2,{message:'我想订场',credentialId:'credential-a',answers:['后天'],askedFields:['target_date'],scopeLabel:'羽毛球'});
  expect(proposalApi.generate).toHaveBeenNthCalledWith(3,{message:'我想订场',credentialId:'credential-a',answers:['后天','14-16'],askedFields:['target_date','windows_2h'],scopeLabel:'羽毛球'});
  expect(wrapper.text()).toContain('日期');expect(wrapper.text()).toContain('后天');
 });

 it('restores the latest server conversation after remount and continues with its id',async()=>{
  const saved={conversation_id:'conversation-identifier-123',business_date:'2026-10-18',message:'想订场',answers:['后天'],asked_fields:['target_date'],scope_label:'羽毛球',response_history:[
   {...ask('想订哪一天？',{asking:'target_date',heading:'日期'}),trace_event:{submitted_title:'提交预约需求',result_title:'还缺一项信息',result_detail:'服务端保存的轨迹。',at_utc_ms:Date.UTC(2026,9,18,3,0)}},
   ask('2小时要哪个时间段？',{asking:'windows_2h',heading:'2小时时段',workflow_trace:[{stage:'模型理解',detail:'已加载历史并识别日期。'}]}),
  ]};
  const config=fixture();config.proposalApi.restore=vi.fn(async()=>({conversation:saved}));
  const {wrapper,proposalApi}=await mountAssistant(config);
  expect(wrapper.text()).toContain('想订场');expect(wrapper.text()).toContain('后天');expect(wrapper.text()).toContain('2小时要哪个时间段？');expect(wrapper.text()).toContain('服务端保存的轨迹。');expect(wrapper.text()).toContain('已加载历史并识别日期。');
  expect(wrapper.text()).not.toContain('已保存的对话暂时无法恢复');
  await reply(wrapper,'14-16');
  expect(proposalApi.generate).toHaveBeenCalledWith(expect.objectContaining({conversationId:'conversation-identifier-123',answers:['后天','14-16'],askedFields:['target_date','windows_2h']}));
 });

 it('closes a pending restored conversation when the user restarts',async()=>{
  const saved={conversation_id:'conversation-identifier-123',business_date:'2026-10-18',message:'旧的预约意向',answers:[],asked_fields:[],scope_label:'羽毛球',response_history:[ask('想订哪一天？')]};
  let resolveRestore;
  const config=fixture();config.proposalApi.restore=vi.fn(()=>new Promise(resolve=>{resolveRestore=resolve;}));
  const {wrapper,proposalApi}=await mountAssistant(config);
  await wrapper.get('[data-testid="restart-conversation"]').trigger('click');
  resolveRestore({conversation:saved});
  await flushPromises();
  expect(wrapper.get('[data-testid="proposal-message"]').element.value).toBe('');
  expect(wrapper.text()).not.toContain('旧的预约意向');
  expect(proposalApi.close).toHaveBeenCalledWith(saved.conversation_id,'credential-a');
 });

 it('needs a credential before it can ask anything',async()=>{
  const {wrapper,proposalApi}=await mountAssistant(fixture({credentialId:''}));
  await send(wrapper,'后天 14-16');
  expect(proposalApi.generate).not.toHaveBeenCalled();expect(wrapper.text()).toContain('先在右上角选择预约凭据');
 });

 it('keeps the message and says so when the request fails',async()=>{
  const config=fixture();config.proposalApi.generate=vi.fn(async()=>{throw {code:'provider_timeout'};});
  const {wrapper}=await mountAssistant(config);await send(wrapper,'后天 14-16');
  expect(wrapper.text()).toContain('整理失败');expect(wrapper.get('[data-testid="proposal-message"]').element.value).toBe('后天 14-16');
 });

 it('explains a refused command and offers no save',async()=>{
  const config=fixture({result:{status:'unsupported',questions:['当前只能整理并保存预约队列。'],proposal:null,conversation:conversation({phase:'unsupported',asking:null})}});
  const {wrapper}=await mountAssistant(config);await send(wrapper,'帮我直接付款');
  expect(wrapper.text()).toContain('当前只能整理并保存预约队列。');expect(wrapper.find('[data-testid="confirm-save-proposal"]').exists()).toBe(false);
 });

 it('tells the user when the answer budget is spent instead of silently ignoring the send',async()=>{
  const {wrapper,proposalApi}=await mountAssistant(fixture({result:ask('再说一次？')}));
  await send(wrapper,'想订场');
  for(let i=0;i<20;i++)await reply(wrapper,`答${i}`);
  expect(proposalApi.generate).toHaveBeenCalledTimes(21);
  await reply(wrapper,'第二十一次');
  expect(proposalApi.generate).toHaveBeenCalledTimes(21);expect(wrapper.text()).toContain('补充的次数已用完');
 });
});

describe('queue assistant: preview and save',()=>{
 it('previews the ordered queue with the priority rule and the schedule',async()=>{
  const {wrapper,planApi}=await mountAssistant();await send(wrapper,'后天 14-16 和 18-20，1号4号场');
  const rows=wrapper.findAll('[data-testid="queue-entries"] li');
  expect(rows.map(li=>li.get('.queue-index').text())).toEqual(['1','2','3','4']);
  expect(rows.map(li=>li.text().slice(1))).toEqual(['2小时 14:00-16:00 1号场','2小时 14:00-16:00 4号场','2小时 18:00-20:00 1号场','2小时 18:00-20:00 4号场']);
  expect(wrapper.get('[data-testid="queue-order-note"]').text()).toContain('抢到第一个就停');
  expect(wrapper.get('[data-testid="queue-schedule"]').text()).toContain('07:30');
  expect(wrapper.text()).not.toContain('分钟');
  expect(planApi.saveQueue).not.toHaveBeenCalled();
 });

 it('saves through the manual-queue endpoint with the version it was built on',async()=>{
  const config=fixture({result:{...ready({},{base_version:3,existing_count:2,replaces_existing:true}),conversation_id:'saved-conversation-123'}});
  const {wrapper,planApi}=await mountAssistant(config);await send(wrapper,'后天 14-16 和 18-20，1号4号场');
  expect(wrapper.get('[data-testid="replace-warning"]').text()).toContain('已经有 2 项候选');
  await wrapper.get('[data-testid="confirm-save-proposal"]').trigger('click');await flushPromises();
  expect(planApi.saveQueue).toHaveBeenCalledWith('2026-10-20',3,ENTRIES,'credential-a');
  expect(config.proposalApi.close).toHaveBeenCalledWith('saved-conversation-123','credential-a','saved');
  expect(wrapper.text()).toContain('队列已保存 · 10月20日 周二 · 共 4 项候选');
  expect(wrapper.emitted('saved')[0][0].target_date).toBe('2026-10-20');expect(wrapper.emitted('refresh-request')).toHaveLength(1);
  expect(wrapper.find('[data-testid="queue-preview"]').exists()).toBe(false);
 });

 it('shows the model review as advice and a skipped review as a note',async()=>{
  const {wrapper}=await mountAssistant(fixture({result:ready({},{warnings:['你提到的 3 号场没有出现在队列里'],review:{state:'reviewed',attempts:1}})}));
  await send(wrapper,'后天 14-16，1号3号场');
  expect(wrapper.get('[data-testid="review-warnings"]').text()).toContain('仅供参考');
  expect(wrapper.get('[data-testid="review-warnings"]').text()).toContain('3 号场');
  expect(wrapper.get('[data-testid="confirm-save-proposal"]').element.disabled).toBe(false);
  const skipped=await mountAssistant(fixture({result:ready({},{review:{state:'skipped',note:'队列没有经过模型复核（尚未配置模型）。'}})}));
  await send(skipped.wrapper,'后天 14-16');expect(skipped.wrapper.text()).toContain('尚未配置模型');
 });

 it('warns when the date will not be handled automatically',async()=>{
  const {wrapper}=await mountAssistant(fixture({result:ready({},{schedule:{state:'not_automatic',text:'这一天已经不会再自动执行。'}})}));
  await send(wrapper,'明天 14-16');
  expect(wrapper.get('[data-testid="queue-schedule"]').classes()).toContain('is-warn');
 });

 it('disables saving when the description changes after the draft was built',async()=>{
  const {wrapper,planApi}=await mountAssistant();await send(wrapper,'后天 14-16');
  await wrapper.get('[data-testid="proposal-message"]').setValue('改成大后天');
  expect(wrapper.get('[data-testid="confirm-save-proposal"]').element.disabled).toBe(true);expect(planApi.saveQueue).not.toHaveBeenCalled();
 });

 it('does not start a second save while one is in flight',async()=>{
  let release;const config=fixture({saveQueue:vi.fn(()=>new Promise(r=>{release=r;}))});
  const {wrapper,planApi}=await mountAssistant(config);await send(wrapper,'后天 14-16');
  const save=wrapper.get('[data-testid="confirm-save-proposal"]');await save.trigger('click');await save.trigger('click');await flushPromises();
  expect(planApi.saveQueue).toHaveBeenCalledTimes(1);expect(save.element.disabled).toBe(true);
  release({queue:{}});await flushPromises();expect(wrapper.text()).toContain('队列已保存');
 });

 it('treats a version conflict as stale and regenerates from the latest queue',async()=>{
  const config=fixture({result:{...ready(),conversation_id:'stale-conversation-123456'},saveQueue:vi.fn().mockRejectedValueOnce({status:409,code:'plan_version_conflict'})});
  const {wrapper,planApi,proposalApi}=await mountAssistant(config);await send(wrapper,'后天 14-16');
  await wrapper.get('[data-testid="confirm-save-proposal"]').trigger('click');await flushPromises();
  expect(wrapper.text()).toContain('刚被改过');expect(wrapper.get('[data-testid="confirm-save-proposal"]').element.disabled).toBe(true);
  await wrapper.get('[data-testid="regenerate"]').trigger('click');await flushPromises();
  expect(proposalApi.generate).toHaveBeenCalledTimes(2);expect(proposalApi.generate.mock.calls[1][0]).toMatchObject({regenerate:true,answers:[],askedFields:[]});expect(planApi.saveQueue).toHaveBeenCalledTimes(1);
  expect(wrapper.get('[data-testid="confirm-save-proposal"]').element.disabled).toBe(false);
 });

 it('preserves a multi-turn conversation when regenerating after a version conflict',async()=>{
  const conversationId='multi-turn-conversation-12345';
  const withId=result=>({...result,conversation_id:conversationId});
  const config=fixture({saveQueue:vi.fn().mockRejectedValueOnce({status:409,code:'plan_version_conflict'})});
  config.proposalApi.generate=vi.fn()
   .mockResolvedValueOnce(withId(ask('想订哪一天？',{asking:'target_date',heading:'日期'})))
   .mockResolvedValueOnce(withId(ask('两小时选哪些场地？',{asking:'courts_2h',heading:'2小时场地'})))
   .mockResolvedValueOnce(withId(ready()))
   .mockResolvedValueOnce(withId(ready({},{base_version:2})));
  const {wrapper,proposalApi}=await mountAssistant(config);
  await send(wrapper,'我想订场');await reply(wrapper,'后天');await reply(wrapper,'1号场');
  await wrapper.get('[data-testid="confirm-save-proposal"]').trigger('click');await flushPromises();
  await wrapper.get('[data-testid="regenerate"]').trigger('click');await flushPromises();
  expect(proposalApi.generate).toHaveBeenCalledTimes(4);
  expect(proposalApi.generate.mock.calls[3][0]).toMatchObject({
   conversationId,answers:['后天','1号场'],askedFields:['target_date','courts_2h'],regenerate:true,
  });
  expect(wrapper.get('[data-testid="confirm-save-proposal"]').element.disabled).toBe(false);
 });

 it('keeps the draft when the server rejects the queue',async()=>{
  const config=fixture({saveQueue:vi.fn().mockRejectedValueOnce({status:400,code:'invalid_plan'})});
  const {wrapper}=await mountAssistant(config);await send(wrapper,'后天 14-16');
  await wrapper.get('[data-testid="confirm-save-proposal"]').trigger('click');await flushPromises();
  expect(wrapper.text()).toContain('队列未保存');expect(wrapper.find('[data-testid="queue-preview"]').exists()).toBe(true);
 });

 it('checks the stored queue after a lost response instead of guessing',async()=>{
  const landed={queue:{target_date:'2026-10-20',credential_id:'credential-a',version:1,candidates:ENTRIES.map(e=>({duration_minutes:e.duration_minutes,preferred_start_times:[e.start_time],court_preferences:[e.court_preference],query_scope_label:e.scope_label}))}};
  const config=fixture({saveQueue:vi.fn().mockRejectedValue({kind:'network',status:0}),queue:vi.fn(async()=>landed)});
  const {wrapper,planApi}=await mountAssistant(config);await send(wrapper,'后天 14-16');
  await wrapper.get('[data-testid="confirm-save-proposal"]').trigger('click');await flushPromises();
  expect(planApi.queue).toHaveBeenCalledWith('2026-10-20','credential-a');expect(wrapper.text()).toContain('队列已保存');
  const lost=fixture({saveQueue:vi.fn().mockRejectedValue({kind:'timeout',status:0}),queue:vi.fn(async()=>({queue:{candidates:[]}}))});
  const second=await mountAssistant(lost);await send(second.wrapper,'后天 14-16');
  await second.wrapper.get('[data-testid="confirm-save-proposal"]').trigger('click');await flushPromises();
  expect(second.wrapper.text()).toContain('保存结果暂时无法确认');expect(second.wrapper.find('[data-testid="queue-preview"]').exists()).toBe(true);
  expect(second.wrapper.get('[data-testid="confirm-save-proposal"]').element.disabled).toBe(false);
 });
});

describe('queue assistant: hand-off, notices and sessions',()=>{
 it('hands over to manual selection when the server gives up, and locks the answer box',async()=>{
  const escalation={kind:'stalled',field:'courts_2h',message:'这一项我连续几次都没能确认。',prefill:{target_date:'2026-10-24'}};
  const config=fixture({result:ask(escalation.message,{phase:'escalated',escalation})});
  const {wrapper}=await mountAssistant(config);await send(wrapper,'想订场');
  expect(wrapper.get('[data-testid="escalation-card"]').text()).toContain('2026年10月24日');
  expect(wrapper.find('[data-testid="proposal-answer"]').exists()).toBe(false);expect(wrapper.find('[data-testid="confirm-save-proposal"]').exists()).toBe(false);
  await wrapper.get('[data-testid="open-manual"]').trigger('click');
  expect(wrapper.emitted('manual-request')).toEqual([[{target_date:'2026-10-24'}]]);
  await wrapper.get('[data-testid="escalation-restart"]').trigger('click');
  expect(wrapper.find('[data-testid="escalation-card"]').exists()).toBe(false);expect(wrapper.get('[data-testid="proposal-message"]').element.value).toBe('');
 });

 it('shows server notices as assistant messages and drops them on restart',async()=>{
  const note='我只记录你想在开放时自动预约的意向。';
  const {wrapper}=await mountAssistant(fixture({result:ready({notices:[note]})}));await send(wrapper,'到点自动预约');
  expect(wrapper.get('[data-testid="conversation-notice"]').text()).toBe(note);
  await wrapper.get('[data-testid="cancel-proposal"]').trigger('click');await wrapper.get('[data-testid="restart-conversation"]').trigger('click');
  expect(wrapper.find('[data-testid="conversation-notice"]').exists()).toBe(false);
 });

 it('ignores results returned after the session or CSRF token changes',async()=>{
  let resolve;const config=fixture();config.proposalApi.generate=vi.fn(()=>new Promise(r=>{resolve=r;}));
  const {wrapper,session}=await mountAssistant(config);
  await wrapper.get('[data-testid="proposal-message"]').setValue('我的文本');await wrapper.get('[data-testid="generate-proposal"]').trigger('click');
  session.csrfToken='csrf-b';await flushPromises();resolve(ready());await flushPromises();
  expect(wrapper.find('[data-testid="queue-preview"]').exists()).toBe(false);expect(wrapper.get('[data-testid="proposal-message"]').element.value).toBe('我的文本');
 });

 it('clears the conversation when the account or credential changes',async()=>{
  const {wrapper,session}=await mountAssistant(fixture({result:ask('想订哪一天？')}));
  await send(wrapper,'用户A的私有安排');session.user={user_id:'user-b'};await flushPromises();
  expect(wrapper.get('[data-testid="proposal-message"]').element.value).toBe('');expect(wrapper.text()).not.toContain('想订哪一天？');
  await wrapper.setProps({credentialId:'credential-b'});expect(wrapper.find('[data-testid="queue-preview"]').exists()).toBe(false);
 });

 it('lets users edit the original request, and only clears answers after confirmation',async()=>{
  const config=fixture();config.proposalApi.generate=vi.fn().mockResolvedValue(structuredClone(ask('想订哪一天？')));
  const {wrapper,proposalApi}=await mountAssistant(config);
  await send(wrapper,'想订场');await reply(wrapper,'后天');
  await wrapper.findAll('button').find(b=>b.text()==='修改原描述').trigger('click');
  await wrapper.get('[data-testid="proposal-message"]').setValue('改成下周六');
  expect(wrapper.text()).toContain('描述已变化');expect(wrapper.get('[data-testid="generate-proposal"]').element.disabled).toBe(true);
  await wrapper.findAll('button').find(b=>b.text()==='保留原描述').trigger('click');
  expect(wrapper.get('.chat-message-list').text()).toContain('后天');
  await wrapper.findAll('button').find(b=>b.text()==='修改原描述').trigger('click');
  await wrapper.get('[data-testid="proposal-message"]').setValue('改成下周六');
  await wrapper.findAll('button').find(b=>b.text()==='清除回答并使用新描述').trigger('click');
  expect(wrapper.get('[data-testid="proposal-message"]').element.value).toBe('改成下周六');expect(wrapper.get('.chat-message-list').text()).not.toContain('后天');
  expect(proposalApi.generate).toHaveBeenCalledTimes(2);
 });
});

describe('queue assistant: save safety regressions',()=>{
 it('cannot save an old draft while replacement text awaits confirmation',async()=>{
  const config=fixture();config.proposalApi.generate=vi.fn().mockResolvedValueOnce(ask('几号场？',{asking:'courts_2h'})).mockResolvedValueOnce(ready());
  const {wrapper,planApi}=await mountAssistant(config);await send(wrapper,'后天14-16');await reply(wrapper,'1号场');
  await wrapper.get('[data-testid="proposal-message"]').setValue('改成下周六18-20');
  expect(wrapper.text()).toContain('描述已变化');expect(wrapper.get('[data-testid="confirm-save-proposal"]').element.disabled).toBe(true);
  await wrapper.get('[data-testid="confirm-save-proposal"]').trigger('click');expect(planApi.saveQueue).not.toHaveBeenCalled();
  await wrapper.findAll('button').find(b=>b.text()==='保留原描述').trigger('click');
  expect(wrapper.get('[data-testid="confirm-save-proposal"]').element.disabled).toBe(false);
 });

 it('requires a loaded and unchanged query category before saving',async()=>{
  const config=fixture({result:{...ready(),conversation_id:'scope-conversation-123456'},scopeLabel:''});const {wrapper,planApi}=await mountAssistant(config);await send(wrapper,'后天14-16');
  expect(wrapper.get('[data-testid="confirm-save-proposal"]').element.disabled).toBe(true);
  await wrapper.setProps({scopeLabel:'羽毛球'});expect(wrapper.get('[data-testid="confirm-save-proposal"]').element.disabled).toBe(true);
  await wrapper.get('[data-testid="regenerate"]').trigger('click');await flushPromises();
  expect(wrapper.get('[data-testid="confirm-save-proposal"]').element.disabled).toBe(false);expect(planApi.saveQueue).not.toHaveBeenCalled();
 });

 it('does not claim a lost save succeeded when scope, date, credential or version differs',async()=>{
  const candidates=ENTRIES.map(e=>({duration_minutes:e.duration_minutes,preferred_start_times:[e.start_time],court_preferences:[e.court_preference],query_scope_label:'羽毛球'}));
  const base={target_date:'2026-10-20',credential_id:'credential-a',version:1,candidates};
  for(const changed of [{candidates:candidates.map(c=>({...c,query_scope_label:null}))},{target_date:'2026-10-21'},{credential_id:'credential-b'},{version:9}]){
   const config=fixture({saveQueue:vi.fn().mockRejectedValue({kind:'network',status:0}),queue:vi.fn(async()=>({queue:{...base,...changed}}))});
   const {wrapper}=await mountAssistant(config);await send(wrapper,'后天14-16');await wrapper.get('[data-testid="confirm-save-proposal"]').trigger('click');await flushPromises();
   expect(wrapper.emitted('saved')).toBeUndefined();expect(wrapper.text()).toContain('保存结果暂时无法确认');expect(wrapper.find('[data-testid="queue-preview"]').exists()).toBe(true);
  }
 });
});


describe('contextual conversation after preview',()=>{
 it('keeps the conversation and its preview editable instead of starting over',async()=>{
  const config=fixture({result:{...ready(),conversation_id:'contextual-conversation-12345'}});
  const {wrapper,proposalApi}=await mountAssistant(config);
  await send(wrapper,'10月26日只抢2小时14-16，1号场');
  expect(wrapper.find('[data-testid="proposal-answer"]').exists()).toBe(true);
  expect(wrapper.get('[data-testid="confirm-save-proposal"]').attributes('disabled')).toBeUndefined();
  await wrapper.get('[data-testid="proposal-answer"]').setValue('去掉1号场，再加4号场');
  expect(wrapper.get('[data-testid="confirm-save-proposal"]').attributes('disabled')).toBeDefined();
  await wrapper.get('[data-testid="continue-proposal"]').trigger('click');await flushPromises();
  expect(proposalApi.generate).toHaveBeenLastCalledWith(expect.objectContaining({
   conversationId:'contextual-conversation-12345',answers:['去掉1号场，再加4号场'],askedFields:[null],
  }));
  expect(wrapper.get('[data-testid="proposal-answer"]').element.value).toBe('');
 });
 it('allows a short answer after a question-only turn without repeating the old question',async()=>{
  const config=fixture({result:{...ask('',{asking:'courts_2h',contextual_reply:'还缺场地。'}),questions:[],conversation_id:'contextual-conversation-12345'}});
  const {wrapper}=await mountAssistant(config);
  await send(wrapper,'我还缺什么？');
  expect(wrapper.find('[data-testid="proposal-answer"]').exists()).toBe(true);
  expect(wrapper.text()).toContain('还缺场地');
 });
});
