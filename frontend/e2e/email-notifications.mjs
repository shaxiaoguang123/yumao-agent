import { fixtures, viewports } from './fixtures.mjs';

export async function runEmailNotifications(qa) {
  const { scenario, BASE, check, screenshot, layout } = qa;
  const readyCredentials=fixtures.map(item=>({...item,has_payment_password:true}));
  for (const viewport of viewports.filter(item => [390, 1440].includes(item.width))) {
    await scenario(`email-notification-settings-${viewport.name}`, 'user', async ctx => {
      await ctx.page.goto(BASE + '/plans');
      await ctx.page.getByTestId('plan-tab-current').waitFor();
      await ctx.page.getByTestId('plan-tab-current').click();
      await ctx.page.locator('.execution-settings-disclosure > summary').click();
      const panel=ctx.page.locator('.email-notification-settings');
      await panel.waitFor();
      check(ctx.name,'shows the configured recipient, previous-evening reminder and 08:00 result time',
        await panel.locator('input[type="email"]').inputValue()==='notify@example.invalid'
          && await panel.locator('input[type="time"]').inputValue()==='20:00'
          && (await panel.innerText()).includes('08:00'));
      await panel.locator('input[type="checkbox"]').uncheck();
      await panel.locator('input[type="time"]').fill('19:45');
      await panel.getByRole('button',{name:'保存邮件通知设置',exact:true}).click();
      await panel.getByRole('status').getByText('邮箱通知已关闭。',{exact:true}).waitFor();
      const save=ctx.state.requests.find(item=>item.path==='/api/booking-execution/email-notifications'&&item.method==='PUT');
      check(ctx.name,'preference update is CSRF protected and saves the selected time',save?.csrfValid===true
        &&ctx.state.emailNotificationSettings.enabled===false
        &&ctx.state.emailNotificationSettings.reminder_time==='19:45');
      await panel.getByRole('button',{name:'发送测试邮件',exact:true}).click();
      await panel.getByRole('status').getByText(/测试邮件已被 Cloudflare 接受/).waitFor();
      check(ctx.name,'test mail is an explicit CSRF-protected action',ctx.state.emailNotificationTestSends===1
        &&ctx.state.requests.find(item=>item.path==='/api/booking-execution/email-notifications/test')?.csrfValid===true);
      await layout(ctx);await screenshot(ctx,ctx.name);
    },{credentials:readyCredentials,emailNotificationAvailable:true},viewport);
  }

  await scenario('email-notification-not-owner-hidden','admin',async ctx=>{
    await ctx.page.goto(BASE+'/plans');
    await ctx.page.getByTestId('plan-tab-current').waitFor();
    await ctx.page.getByTestId('plan-tab-current').click();
    await ctx.page.locator('.execution-settings-disclosure > summary').click();
    await ctx.page.locator('.execution-settings').waitFor();
    check(ctx.name,'other accounts do not see the designated owner mailbox or notification settings',
      await ctx.page.locator('.email-notification-settings').count()===0);
  },{credentials:readyCredentials});
}
