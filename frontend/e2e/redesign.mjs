import { fixtures, viewports } from './fixtures.mjs';

const planReadyCredentials = fixtures.map((item) => item.credential_id === 'visual-confirmed'
  ? { ...item, has_payment_password: true }
  : item);

export async function runRedesign(qa) {
 const {scenario,BASE,check,count,layout,screenshot,waitCredentials}=qa;
 for(const viewport of viewports) await scenario(`redesign-credential-discovery-${viewport.name}`,'user',async ctx=>{
  await ctx.page.goto(BASE+'/credentials');await waitCredentials(ctx.page);
  const reads=count(ctx,'/api/credentials','GET');
  await ctx.page.getByTestId('rotate-visual-confirmed').click();
  await ctx.page.getByTestId('rotation-token').fill('synthetic-hidden-draft');
  await ctx.page.getByLabel('搜索凭据名称').fill('no-match');
  await ctx.page.getByLabel('搜索凭据名称').fill('');
  check(ctx.name,'hiding a card clears its sensitive rotation draft without sending a mutation',await ctx.page.getByTestId('rotation-token').count()===0&&count(ctx,'/api/credentials/visual-confirmed/rotate-token')===0);

  await ctx.page.getByLabel('搜索凭据名称').fill('已确认');
  check(ctx.name,'local search matches the complete label',await ctx.page.locator('.credential-card').count()===1);
  await ctx.page.getByLabel('搜索凭据名称').fill('no-match');
  check(ctx.name,'no-match is distinct from successful API-empty',await ctx.page.getByText('没有匹配的凭据。请调整名称或状态筛选。').isVisible()&&await ctx.page.locator('.empty-state').count()===0);
  await ctx.page.getByLabel('搜索凭据名称').fill('');await ctx.page.getByLabel('凭据状态',{exact:true}).selectOption('disabled');
  check(ctx.name,'disabled filter is local and leaves API reads unchanged',await ctx.page.locator('.credential-card').count()===1&&count(ctx,'/api/credentials','GET')===reads);
  await ctx.page.getByLabel('凭据状态',{exact:true}).selectOption('all');
  const card=ctx.page.getByTestId('credential-card-visual-confirmed');
  await card.locator('.validation-record > summary').click();
  check(ctx.name,'verification details remain accessible on explicit expansion',await card.getByText('最近发起的验证',{exact:true}).isVisible());
  check(ctx.name,'automatic execution schedule is no longer on credential management',await ctx.page.getByText('自动执行时间',{exact:true}).count()===0&&count(ctx,'/api/booking-execution/credentials/visual-confirmed/settings','GET')===0);
  const restoreResponse=ctx.page.waitForResponse(response=>{const url=new URL(response.url());return url.pathname==='/api/planning/queue-conversations'&&response.request().method()==='GET';});
  await ctx.page.goto(BASE+'/plans');
  await ctx.page.getByTestId('plan-tab-agent').click();
  const restoredConversation=await restoreResponse;
  check(ctx.name,'Agent restores an empty conversation for the active credential',restoredConversation.ok()&&(await restoredConversation.json()).conversation===null);
  await ctx.page.getByTestId('plan-tab-current').click();
  const settings=ctx.page.locator('#plan-panel-current [aria-labelledby="execution-settings-title"]');
  await settings.locator('.execution-settings-form').waitFor();
  await settings.getByLabel('队列复核时间').fill('01:15');
  await settings.getByRole('button',{name:'保存执行设置'}).click();
  await settings.getByText('已保存；执行器启用后，你名下所有 Token 会使用这组设置。',{exact:true}).waitFor();
  check(ctx.name,'user-shared schedule saves through CSRF-protected API',count(ctx,'/api/booking-execution/settings','PUT')===1&&ctx.state.requests.filter(item=>item.path==='/api/booking-execution/settings'&&item.method==='PUT').every(item=>item.csrfValid===true));
  await layout(ctx);await screenshot(ctx,ctx.name);
 },{credentials:planReadyCredentials},viewport);

 for(const viewport of viewports) await scenario(`redesign-complete-mobile-routes-${viewport.name}`,'admin',async ctx=>{
  await ctx.page.goto(BASE+'/admin');
  await ctx.page.getByRole('heading',{name:'用户管理',exact:true}).waitFor();
  await ctx.page.locator('.admin-user-table').waitFor();
  if(viewport.width<=640){
   check(ctx.name,'admin users become readable cards on phones',await ctx.page.locator('.admin-user-table thead').evaluate(node=>getComputedStyle(node).display)==='none'&&await ctx.page.locator('.admin-user-table td[data-label]').count()>=4);
  }
  await layout(ctx);await screenshot(ctx,`${ctx.name}-admin-users`);

  await ctx.page.goto(BASE+'/settings/ai-models');
  await ctx.page.locator('#ai-models-heading').waitFor();
  await ctx.page.getByText('合成 DeepSeek',{exact:true}).waitFor();
  await layout(ctx);await screenshot(ctx,`${ctx.name}-ai-models`);

  await ctx.page.goto(BASE+'/plans');
  await ctx.page.getByTestId('plan-tab-query').waitFor();
  await layout(ctx);await screenshot(ctx,`${ctx.name}-plans-query`);
  await ctx.page.getByTestId('plan-tab-manual').click();await layout(ctx);
  await ctx.page.getByTestId('plan-tab-agent').click();
  await ctx.page.getByRole('heading',{name:'预约助手',exact:true}).waitFor();
  const preview=ctx.page.locator('.proposal-chat .queue-preview');
  await preview.getByText('队列预览',{exact:true}).waitFor();
  const previewGeometry=await ctx.page.evaluate(()=>{const preview=document.querySelector('.proposal-chat .queue-preview')?.getBoundingClientRect();const messages=document.querySelector('.proposal-chat-messages')?.getBoundingClientRect();return preview&&messages?{preview:{top:preview.top,left:preview.left,right:preview.right,width:preview.width},messages:{top:messages.top,left:messages.left,right:messages.right,width:messages.width},viewport:document.documentElement.clientWidth}:null;});
  check(ctx.name,'Agent queue preview remains visible without horizontal squeeze',Boolean(previewGeometry)&&previewGeometry.preview.left>=0&&previewGeometry.preview.right<=previewGeometry.viewport+1&&(viewport.width>1024||previewGeometry.preview.top<=previewGeometry.messages.top),{previewGeometry});
  await layout(ctx);await screenshot(ctx,`${ctx.name}-plans-agent`);
  await ctx.page.getByTestId('plan-tab-current').click();
  const help=ctx.page.getByLabel('查看执行时间和延迟说明');
  await help.waitFor();await help.focus();
  check(ctx.name,'scheduler help opens from keyboard focus',await ctx.page.getByRole('tooltip').isVisible());
  await ctx.page.getByText('抢票结果',{exact:true}).click();
  await layout(ctx);await screenshot(ctx,`${ctx.name}-plans-current`);
 },{credentials:planReadyCredentials},viewport);
}
