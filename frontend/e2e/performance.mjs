import { fixtures, viewports } from './fixtures.mjs';

const credentials=fixtures.map(item=>item.credential_id==='visual-confirmed'?{...item,has_payment_password:true}:item);

export async function runPerformance(qa){
 const {scenario,BASE,check,count,layout,screenshot}=qa;
 for(const viewport of viewports.filter(item=>[390,1440].includes(item.width))){
  const queue={plan_id:'synthetic-executed-queue',current_revision_id:'synthetic-queue-revision-8',version:8,
   target_date:'2026-10-17',credential_id:'visual-confirmed',plan_status:'draft',can_open_selection:true,
   candidates:[{duration_minutes:120,preferred_start_times:['14:00'],court_preferences:['6号场'],query_scope_label:'羽毛球'}]};
  const run={run_id:'synthetic-successful-run',target_date:queue.target_date,source_plan_id:queue.plan_id,
   source_version:8,source_revision_id:queue.current_revision_id,state:'running',candidate_count:1,
   candidates:[{scope_label:'羽毛球',court_preference:'6号场',start_time:'14:00',end_time:'16:00',duration_minutes:120}],
   reconciliation:{retained_candidate_count:1,discarded_candidate_counts:{}},stages:[]};
  await scenario(`execution-plan-status-${viewport.name}`,'user',async ctx=>{
   await ctx.page.goto(BASE+'/plans');await ctx.page.getByTestId('plan-tab-current').waitFor();
   check(ctx.name,'hidden execution panels do not query run state',count(ctx,`/api/booking-execution/credentials/visual-confirmed/queues/${queue.target_date}`,'GET')===0);
   await ctx.page.getByTestId('plan-tab-current').click();
   const label=ctx.page.locator('.ticket-state');
   await ctx.page.getByText('执行中',{exact:true}).first().waitFor();await ctx.page.getByTestId('queue-filter-all').click();await label.waitFor();
   check(ctx.name,'plan card and execution panel initially report the same running state',await label.innerText()==='执行中'&&(await ctx.page.locator('.execution-snapshot summary').innerText()).includes('执行中'));
   ctx.state.executionRuns['visual-confirmed'][queue.target_date].state='succeeded';
   await ctx.page.getByRole('button',{name:'重新读取抢票计划',exact:true}).click();
   await ctx.page.getByText('已执行 · 抢票成功',{exact:true}).waitFor();
   check(ctx.name,'refresh updates both statuses without a queue revision change',await label.innerText()==='已执行 · 抢票成功'&&(await ctx.page.locator('.execution-snapshot summary').innerText()).includes('已执行 · 抢票成功'));
   check(ctx.name,'summary refreshes require no per-card detail requests',count(ctx,`/api/booking-execution/credentials/visual-confirmed/queues/${queue.target_date}`,'GET')===0);
   await ctx.page.locator('.execution-snapshot summary').click();await ctx.page.locator('.execution-snapshot-body').waitFor();
   check(ctx.name,'expanding reads one exact revision detail',count(ctx,`/api/booking-execution/credentials/visual-confirmed/queues/${queue.target_date}`,'GET')===1);
   await ctx.page.getByTestId('plan-tab-manual').click();ctx.state.executionRuns['visual-confirmed'][queue.target_date].state='needs_attention';
   await ctx.page.getByTestId('plan-tab-current').click();await ctx.page.getByText('需要关注',{exact:true}).waitFor();
   check(ctx.name,'returning to the plan tab reads the latest execution state',await label.innerText()==='需要关注');
   ctx.state.executionRuns['visual-confirmed'][queue.target_date].state='succeeded';
   await ctx.page.getByRole('button',{name:'重新读取抢票计划',exact:true}).click();await ctx.page.getByText('已执行 · 抢票成功',{exact:true}).waitFor();
   check(ctx.name,'status reads never modify the queue',!ctx.state.requests.some(request=>request.path.startsWith('/api/plans')&&request.method!=='GET'));
   await layout(ctx);await screenshot(ctx,ctx.name);
  },{credentials,manualQueues:[queue],executionRuns:{'visual-confirmed':{[queue.target_date]:run}}},viewport);
 }
 for(const viewport of viewports.filter(item=>[390,1440].includes(item.width)))await scenario(`performance-loading-${viewport.name}`,'user',async ctx=>{
  await ctx.page.goto(BASE+'/plans');await ctx.page.getByTestId('live-availability-grid').waitFor();
  const reads=ctx.state.requests.filter(item=>item.path!=='/api/auth/session');
  check(ctx.name,'query entry uses at most eight business reads',reads.length<=8,{requests:reads});
  check(ctx.name,'credential guard snapshot is reused without skipping its check',count(ctx,'/api/credentials','GET')===1);
  check(ctx.name,'calendar and options are each read once',count(ctx,'/api/booking-window','GET')===1&&count(ctx,'/api/plans/options','GET')===1);
  check(ctx.name,'closed execution settings and unvisited results do not load',count(ctx,'/api/booking-execution/settings','GET')===0&&count(ctx,'/api/booking-execution/successes','GET')===0);
  const grids=count(ctx,'/api/availability/live/grid');
  await ctx.page.getByTestId('plan-tab-agent').click();await ctx.page.locator('.agent-credential-gate[data-state="ready"]').waitFor();
  check(ctx.name,'Agent does not fetch hidden venue inventory',count(ctx,'/api/availability/live/grid')===grids);
  await ctx.page.getByTestId('proposal-message').fill('后天14-16，先保留这条草稿');
  await ctx.page.getByTestId('plan-tab-current').click();await ctx.page.getByTestId('plan-tab-agent').click();
  check(ctx.name,'tab changes preserve the Agent draft and reuse readiness',await ctx.page.getByTestId('proposal-message').inputValue()==='后天14-16，先保留这条草稿'&&count(ctx,'/api/ai/models/visual-model/test')===1);
  await layout(ctx);await screenshot(ctx,ctx.name);
 },{credentials,liveEnabled:true},viewport);

 await scenario('performance-obsolete-date','user',async ctx=>{
  await ctx.page.goto(BASE+'/plans');await ctx.page.getByTestId('live-availability-grid').waitFor();
  let release;
  ctx.state.nextGridBarrier=new Promise(resolve=>{release=resolve;});
  try{
   const oldRequest=ctx.page.waitForRequest(request=>new URL(request.url()).pathname==='/api/availability/live/grid');
   await ctx.page.locator('#plan-panel-query').getByTestId('browse-date-0').click();await oldRequest;
   await ctx.page.locator('#plan-panel-query').getByTestId('browse-date-1').click();
   check(ctx.name,'rapid date changes do not start a competing upstream read',ctx.state.requests.filter(item=>item.path==='/api/availability/live/grid').length===2);
  }finally{release();}
  await Promise.all([...ctx.pendingRoutes]);
  await ctx.page.getByTestId('live-availability-grid').waitFor();
  check(ctx.name,'late response cannot replace the new date',(await ctx.page.getByTestId('live-availability-grid').innerText()).includes('2026-10-16'));
  await screenshot(ctx,ctx.name);
 },{credentials,liveEnabled:true},viewports.find(item=>item.width===390));
}
