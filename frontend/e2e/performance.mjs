import { fixtures, viewports } from './fixtures.mjs';

const credentials=fixtures.map(item=>item.credential_id==='visual-confirmed'?{...item,has_payment_password:true}:item);

export async function runPerformance(qa){
 const {scenario,BASE,check,count,layout,screenshot}=qa;
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
