import { fixtures, viewports } from './fixtures.mjs';
const credentials=fixtures.map(c=>({...c,has_payment_password:true}));
function record(id,date,state,category,version=1,current=true){
 const event=Date.parse(date+'T07:30:08+08:00');
 return {record_id:id,plan_id:id,current_revision_id:id,version,credential_id:'visual-confirmed',target_date:date,
  candidates:[{duration_minutes:120,preferred_start_times:['14:00'],court_preferences:['6号场'],query_scope_label:'羽毛球'}],
  lifecycle:{category,state,label:{waiting:'待复核 · 未执行',running:'执行中',succeeded:'已执行 · 抢票成功',failed:'三轮未成功',missed:'已错过开抢 · 未执行'}[state],opening_at_utc_ms:event-172800000-8000,completed_at_utc_ms:category==='pending'?null:event,event_at_utc_ms:event,is_current_revision:current,current_version:current?version:version+1},
  success:category==='succeeded'?{court_preference:'6号场',start_time:'14:00',end_time:'16:00',confirmed_at_utc_ms:event}:null};
}
export async function runQueueLifecycle(qa){
 const {scenario,BASE,check,layout,screenshot}=qa;
 for(const scheme of ['light','dark'])for(const viewport of viewports.filter(v=>[390,1440].includes(v.width))){
  const queues=[record('wait-far','2026-11-03','waiting','pending'),record('wait-near','2026-11-01','waiting','pending'),record('running','2026-11-04','running','pending'),record('failed','2026-10-19','failed','attention'),record('missed','2026-10-18','missed','attention'),...Array.from({length:23},(_,i)=>record(`success-${i}`,`2026-10-${String(i+1).padStart(2,'0')}`,'succeeded','succeeded',2,false))];
  await scenario(`queue-lifecycle-${scheme}-${viewport.name}`,'user',async ctx=>{
   await ctx.page.emulateMedia({colorScheme:scheme});await ctx.page.goto(BASE+'/plans?tab=current');
   await ctx.page.locator('.ticket-queue-card').nth(2).waitFor();
   check(ctx.name,'pending runs first, then nearest opening',JSON.stringify(await ctx.page.locator('.ticket-card-heading>strong').allTextContents())===JSON.stringify(['2026-11-04','2026-11-01','2026-11-03']));
   check(ctx.name,'opening remains Beijing time in a non-Beijing browser',(await ctx.page.locator('.ticket-times').first().innerText()).includes('11/02 07:30'));
   await layout(ctx);await screenshot(ctx,ctx.name+'-pending');
   await ctx.page.getByTestId('queue-filter-succeeded').click();await ctx.page.locator('.ticket-queue-card').nth(19).waitFor();
   check(ctx.name,'success list pages older records and orders latest first',await ctx.page.locator('.ticket-queue-card').count()===20&&(await ctx.page.locator('.ticket-card-heading>strong').first().innerText())==='2026-10-23');
   check(ctx.name,'historic results retain actual court and disable mutation',await ctx.page.locator('.ticket-success-result').first().innerText().then(t=>t.includes('6号场')&&t.includes('14:00–16:00'))&&await ctx.page.getByRole('button',{name:'调整2026-10-23队列顺序和场地',exact:true}).isDisabled());
   await ctx.page.getByRole('button',{name:'加载更多记录',exact:true}).click();await ctx.page.locator('.ticket-queue-card').nth(22).waitFor();
   check(ctx.name,'all 23 immutable successes are reachable',await ctx.page.locator('.ticket-queue-card').count()===23);
   await ctx.page.getByLabel('抢票计划日期',{exact:true}).fill('2026-10-01');await ctx.page.getByText('1 条记录',{exact:true}).waitFor();
   check(ctx.name,'date filtering applies to successes',await ctx.page.locator('.ticket-card-heading>strong').allTextContents().then(a=>JSON.stringify(a)==='["2026-10-01"]'));
   await ctx.page.getByRole('button',{name:'全部日期',exact:true}).click();await ctx.page.getByTestId('queue-filter-attention').click();await ctx.page.getByText('三轮未成功',{exact:true}).waitFor();
   check(ctx.name,'failed and missed remain distinct in attention',await ctx.page.getByText('已错过开抢 · 未执行',{exact:true}).isVisible());
   await screenshot(ctx,ctx.name+'-attention');
   const popover=ctx.page.locator('#plan-panel-current .credential-popover');await popover.locator('summary').click();
   await ctx.page.getByTestId('selection-credential').filter({visible:true}).selectOption('visual-expired');await ctx.page.getByText('0 条记录',{exact:true}).waitFor();
   check(ctx.name,'Token switch clears another Tokens results',await ctx.page.locator('.ticket-queue-card').count()===0);
  },{credentials,overviewQueues:queues,timezoneId:'America/Los_Angeles'},viewport);
 }
 for(const viewport of viewports.filter(v=>[390,1440].includes(v.width)))await scenario(`theme-manual-${viewport.name}`,'anonymous',async ctx=>{
  await ctx.page.emulateMedia({colorScheme:'light'});await ctx.page.goto(BASE+'/login');await ctx.page.getByLabel('用户名',{exact:true}).waitFor();
  for(const value of ['深色','浅色']){
   await ctx.page.getByLabel('切换外观',{exact:true}).click();await ctx.page.getByLabel(value,{exact:true}).check();
   await ctx.page.reload();await ctx.page.getByLabel('切换外观',{exact:true}).waitFor();
   check(ctx.name,`${value} preference survives a reload`,await ctx.page.evaluate(()=>getComputedStyle(document.documentElement).colorScheme)===(value==='深色'?'dark':'light'));
  }
  await ctx.page.getByLabel('切换外观',{exact:true}).click();await ctx.page.getByLabel('跟随系统',{exact:true}).check();
  await ctx.page.emulateMedia({colorScheme:'dark'});await ctx.page.waitForFunction(()=>getComputedStyle(document.documentElement).colorScheme==='dark');
  check(ctx.name,'return to system removes persisted override',await ctx.page.evaluate(()=>localStorage.getItem('yumao-theme'))===null);
  await layout(ctx);await screenshot(ctx,ctx.name);
 },{},viewport);

 for(const viewport of viewports.filter(v=>[390,1440].includes(v.width))){
  const editable=record('inline-edit','2026-11-05','waiting','pending',4);
  editable.candidates=[
   {duration_minutes:120,preferred_start_times:['16:00'],court_preferences:['2号场'],query_scope_label:'羽毛球'},
   {duration_minutes:120,preferred_start_times:['18:00'],court_preferences:['4号场'],query_scope_label:'羽毛球'},
  ];
  await scenario(`queue-inline-edit-${viewport.name}`,'user',async ctx=>{
   await ctx.page.goto(BASE+'/plans?tab=current');
   const card=ctx.page.locator('.ticket-queue-card').filter({hasText:'2026-11-05'});
   await card.waitFor();
   await card.getByRole('button',{name:'调整2026-11-05队列顺序和场地',exact:true}).click();
   await card.getByRole('button',{name:'将120分钟候选2上移',exact:true}).click();
   check(ctx.name,'moves a candidate within the two-hour queue',
     JSON.stringify(await card.locator('.queue-entry strong').allTextContents())==='["4号场","2号场"]');
   await card.getByRole('button',{name:'移除120分钟候选2',exact:true}).click();
   check(ctx.name,'edits stay inside the two-hour group and leave the selected 4号场 candidate',
     JSON.stringify(await card.locator('.queue-entry strong').allTextContents())==='["4号场"]');
   await layout(ctx);await screenshot(ctx,ctx.name+'-editing');
   await card.getByRole('button',{name:'保存调整',exact:true}).click();
   await card.getByText('队列调整已保存。',{exact:true}).waitFor();
   const saved=ctx.state.requests.find(item=>item.path==='/api/plans/manual-queues/2026-11-05'&&item.method==='PUT');
   check(ctx.name,'saves the new order and removal through the versioned CSRF-protected queue API',
     saved?.csrfValid===true&&saved?.body?.base_version===4&&ctx.state.overviewQueues[0].version===5
      &&ctx.state.overviewQueues[0].candidates.length===1&&ctx.state.overviewQueues[0].candidates[0].court_preferences[0]==='4号场');
   await layout(ctx);await screenshot(ctx,ctx.name);
  },{credentials,overviewQueues:[editable]},viewport);
 }
}
