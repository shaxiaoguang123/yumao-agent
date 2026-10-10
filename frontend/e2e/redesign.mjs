import { viewports } from './fixtures.mjs';
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
  await card.locator('summary').click();
  check(ctx.name,'verification details remain accessible on explicit expansion',await card.getByText('最近发起的验证',{exact:true}).isVisible());
  await layout(ctx);await screenshot(ctx,ctx.name);
 },{},viewport);
}
