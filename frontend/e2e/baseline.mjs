import { SYNTHETIC_CODE, SYNTHETIC_PASSWORD, SYNTHETIC_TOKEN, credential, viewports } from './fixtures.mjs';

// Preserve the 46 original browser scenarios; strengthen ambiguous state assertions.
export async function runBaseline(qa) {
  const { BASE, check, scenario, screenshot, layout, tabs, waitCredentials, count } = qa;
  for (const viewport of viewports) {
    for (const [label, route, role, heading] of [
      ['login','/login','anonymous','登录'], ['register','/register','anonymous','邀请码注册'], ['home','/','user','你好，visual_user'],
      ['credentials','/credentials','user','预约凭据'], ['account','/account','user','账户设置'], ['admin-invitations','/admin/invitations','admin','创建注册邀请码'],
    ]) {
      await scenario(`baseline-${label}-${viewport.name}`, role, async (ctx) => {
        await ctx.page.goto(BASE + route);
        await ctx.page.getByRole('heading', { name: heading, exact: true }).waitFor();
        if (label === 'credentials') await waitCredentials(ctx.page);
        if (label === 'home') await ctx.page.getByText('1 个凭据的账户连续性尚未确认', { exact: false }).waitFor();
        check(ctx.name, 'expected route', new URL(ctx.page.url()).pathname === route);
        check(ctx.name, 'admin navigation role visibility', await ctx.page.getByTestId('admin-invitations-link').count() === (role === 'admin' ? 1 : 0));
        await layout(ctx); await tabs(ctx); await screenshot(ctx, ctx.name);
      }, {}, viewport);
    }
  }
  await scenario('route-permissions', 'anonymous', async (ctx) => {
    for (const route of ['/', '/credentials', '/account', '/admin/invitations']) {
      await ctx.page.goto(BASE + route); await ctx.page.getByRole('heading', { name: '登录', exact: true }).waitFor();
      check(ctx.name, `anonymous ${route} redirects to login`, new URL(ctx.page.url()).pathname === '/login');
    }
    ctx.state.role = 'user';
    await ctx.page.goto(BASE + '/admin/invitations'); await ctx.page.getByRole('heading', { name: '你好，visual_user', exact: true }).waitFor();
    check(ctx.name, 'ordinary user cannot enter admin page or send invitation POST', new URL(ctx.page.url()).pathname === '/' && count(ctx, '/api/admin/invitations') === 0 && await ctx.page.getByTestId('admin-invitations-link').count() === 0);
    ctx.state.role = 'admin'; await ctx.page.goto(BASE + '/admin/invitations'); await ctx.page.getByTestId('create-invitation').waitFor();
    check(ctx.name, 'admin can enter admin page', new URL(ctx.page.url()).pathname === '/admin/invitations');
  });
  await scenario('login-error-and-success', 'anonymous', async (ctx) => {
    await ctx.page.goto(BASE + '/login'); await ctx.page.getByRole('heading', { name: '登录', exact: true }).waitFor();
    await ctx.page.getByRole('button', { name: '登录', exact: true }).click(); check(ctx.name, 'required empty form sends no request', count(ctx, '/api/auth/login') === 0);
    await ctx.page.getByLabel('用户名').fill('visual_user'); await ctx.page.getByLabel('密码', { exact: true }).fill(SYNTHETIC_PASSWORD);
    ctx.state.loginOutcome = 'error'; await ctx.page.getByRole('button', { name: '登录', exact: true }).click(); await ctx.page.getByRole('alert').waitFor();
    check(ctx.name, 'safe invalid-credentials feedback', await ctx.page.getByRole('alert').innerText() === '用户名或密码错误'); await screenshot(ctx, ctx.name);
    ctx.state.loginOutcome = 'success'; await ctx.page.getByRole('button', { name: '登录', exact: true }).click(); await ctx.page.getByRole('heading', { name: '你好，visual_user' }).waitFor();
    check(ctx.name, 'successful login goes home', new URL(ctx.page.url()).pathname === '/');
  }, {}, viewports[2]);
  await scenario('registration-error-and-success', 'anonymous', async (ctx) => {
    await ctx.page.goto(BASE + '/register'); await ctx.page.getByTestId('invite-code').fill(SYNTHETIC_CODE); await ctx.page.getByTestId('username').fill('visual_user'); await ctx.page.getByTestId('password').fill(SYNTHETIC_PASSWORD);
    ctx.state.registerOutcome = 'error'; await ctx.page.getByRole('button', { name: '创建账户' }).click(); await ctx.page.getByRole('alert').waitFor();
    check(ctx.name, 'failure clears invitation/password', await ctx.page.getByTestId('invite-code').inputValue() === '' && await ctx.page.getByTestId('password').inputValue() === ''); await screenshot(ctx, 'registration-error');
    ctx.state.registerOutcome = 'success'; await ctx.page.getByTestId('invite-code').fill(SYNTHETIC_CODE); await ctx.page.getByTestId('password').fill(SYNTHETIC_PASSWORD); await ctx.page.getByRole('button', { name: '创建账户' }).click(); await ctx.page.getByRole('status').waitFor();
    check(ctx.name, 'success clears invitation/password and offers login', await ctx.page.getByTestId('invite-code').inputValue() === '' && await ctx.page.getByTestId('password').inputValue() === '' && await ctx.page.getByRole('link', { name: '返回登录' }).count() === 1); await screenshot(ctx, 'registration-success');
  }, {}, viewports[2]);
  for (const route of ['/', '/credentials']) {
    const pageName = route === '/' ? 'home' : 'credentials';
    await scenario(`${pageName}-loading-empty-error`, 'user', async (ctx) => {
      await ctx.page.goto(BASE + route); await ctx.page.getByText('正在读取凭据状态…').waitFor(); await screenshot(ctx, `${pageName}-loading`);
      await ctx.page.getByText(pageName === 'home' ? '尚未添加预约凭据。' : '暂无预约凭据。添加后可查看 Token 状态和账户连续性。', { exact: true }).waitFor(); await screenshot(ctx, `${pageName}-empty`);
      ctx.state.listError = true; ctx.state.listDelay = 0; await ctx.page.reload();
      await ctx.page.getByText(pageName === 'home' ? '暂时无法读取凭据状态，请稍后重试。' : '上游服务暂时不可用，请稍后重试。', { exact: false }).waitFor(); await screenshot(ctx, `${pageName}-error`);
      check(ctx.name, 'loading, empty and safe failure render', true);
      if (pageName === 'credentials') check(ctx.name, 'F5 failure does not claim a successful empty list', await ctx.page.locator('.empty-state').count() === 0);
    }, { credentials: [], listDelay: 900 }, viewports[2]);
  }
  await scenario('credential-actions', 'user', async (ctx) => {
    await ctx.page.goto(BASE + '/credentials'); await waitCredentials(ctx.page);
    check(ctx.name, 'unresolved/reconfirmation rotation hidden', await ctx.page.getByTestId('rotate-visual-unresolved').count() === 0 && await ctx.page.getByTestId('rotate-visual-reconfirmation').count() === 0);
    ctx.page.once('dialog', async (dialog) => { check(ctx.name, 'irreversible deletion warning', dialog.type() === 'confirm' && dialog.message().includes('无法撤销')); await dialog.dismiss(); });
    await ctx.page.getByTestId('credential-delete-visual-confirmed').click(); check(ctx.name, 'cancel sends no DELETE', count(ctx, '/api/credentials/visual-confirmed', 'DELETE') === 0);
    ctx.state.removeError = true; ctx.page.once('dialog', (dialog) => dialog.accept()); await ctx.page.getByTestId('credential-delete-visual-confirmed').click(); await ctx.page.getByRole('alert').waitFor();
    check(ctx.name, 'failed deletion retains card', await ctx.page.getByTestId('credential-card-visual-confirmed').count() === 1); await screenshot(ctx, 'credential-delete-conflict');
    ctx.state.removeError = false; ctx.page.once('dialog', (dialog) => dialog.accept()); await ctx.page.getByTestId('credential-delete-visual-confirmed').click(); await ctx.page.getByText('凭据已删除。', { exact: true }).waitFor(); await ctx.page.getByTestId('credential-card-visual-confirmed').waitFor({ state: 'detached' });
    check(ctx.name, 'confirmed successful deletion removes card', true);
    await ctx.page.getByTestId('credential-enable-visual-disabled').click(); await ctx.page.getByText('凭据已启用；请重新验证当前 Token。', { exact: true }).waitFor();
    check(ctx.name, 'enable retains confirmed binding and sets separate revalidation', ctx.state.credentials.find((c) => c.credential_id === 'visual-disabled').requires_revalidation && ctx.state.credentials.find((c) => c.credential_id === 'visual-disabled').account_binding_state === 'confirmed');
    await ctx.page.getByTestId('rotate-visual-disabled').click(); await ctx.page.getByTestId('rotation-token').fill(SYNTHETIC_TOKEN); await ctx.page.getByTestId('rotation-cancel').click();
    check(ctx.name, 'rotation cancel clears sensitive input', await ctx.page.getByTestId('rotation-token').count() === 0);
    await ctx.page.getByTestId('rotate-visual-disabled').click(); await ctx.page.getByTestId('rotation-token').fill(SYNTHETIC_TOKEN); ctx.state.rotationError = true; await ctx.page.getByTestId('rotation-submit').click(); await ctx.page.getByText('替换 Token 与当前账户不匹配，原凭据保持不变。', { exact: true }).waitFor();
    check(ctx.name, 'failed rotation clears Token and retains version', await ctx.page.getByTestId('rotation-token').inputValue() === '' && ctx.state.credentials.find((c) => c.credential_id === 'visual-disabled').credential_version === 4);
    await screenshot(ctx, 'credential-rotation-error');
    await ctx.page.getByTestId('credential-token').fill(SYNTHETIC_TOKEN); await ctx.page.getByTestId('credential-label').fill('合成新凭据'); ctx.state.createDelay = 550;
    await ctx.page.locator('[data-testid=credential-create]').evaluate((form) => { form.requestSubmit(); form.requestSubmit(); }); await ctx.page.getByText('验证并保存中…', { exact: true }).waitFor();
    check(ctx.name, 'create in-flight button disabled', await ctx.page.getByText('验证并保存中…', { exact: true }).isDisabled()); await ctx.page.getByText('凭据已添加。', { exact: true }).waitFor();
    check(ctx.name, 'duplicate create protected and Token cleared', count(ctx, '/api/credentials') === 1 && await ctx.page.getByTestId('credential-token').inputValue() === '');
  }, {}, viewports[2]);
  for (const viewport of [viewports[0], viewports[2]]) {
    await scenario(`credential-long-label-${viewport.name}`, 'user', async (ctx) => {
      await ctx.page.goto(BASE + '/credentials'); await waitCredentials(ctx.page); await layout(ctx); await screenshot(ctx, ctx.name);
    }, { credentials: [credential('visual-confirmed', 'Visual_QA_' + 'W'.repeat(118))] }, viewport);
  }
  for (const viewport of [viewports[2], viewports[3]]) {
    await scenario(`admin-success-${viewport.name}`, 'admin', async (ctx) => {
      await ctx.page.goto(BASE + '/admin/invitations'); await ctx.page.getByTestId('create-invitation').waitFor();
      await ctx.page.locator('form').evaluate((form) => { form.requestSubmit(); form.requestSubmit(); }); await ctx.page.getByText('正在创建…', { exact: true }).waitFor();
      check(ctx.name, 'create disabled while pending', await ctx.page.getByTestId('create-invitation').isDisabled()); await screenshot(ctx, `admin-loading-${viewport.name}`);
      await ctx.page.getByTestId('invitation-code').waitFor(); check(ctx.name, 'single successful creation and 24-hour notice', count(ctx, '/api/admin/invitations') === 1 && await ctx.page.getByTestId('create-invitation').isDisabled() && (await ctx.page.locator('main').innerText()).includes('24 小时'));
      await ctx.page.getByTestId('copy-invitation').click(); await ctx.page.getByText('邀请码已复制。', { exact: true }).waitFor();
      check(ctx.name, 'real browser clipboard copy', await ctx.page.evaluate((code) => navigator.clipboard.readText().then((value) => value === code), SYNTHETIC_CODE));
      await layout(ctx); await screenshot(ctx, `admin-result-${viewport.name}`);
      await ctx.page.getByTestId('dismiss-invitation').click(); check(ctx.name, 'dismiss clears invitation', await ctx.page.getByTestId('invitation-code').count() === 0);
      ctx.state.inviteDelay = 0; await ctx.page.getByTestId('create-invitation').click(); await ctx.page.getByTestId('invitation-code').waitFor();
      await ctx.page.getByRole('link', { name: '首页', exact: true }).click(); await ctx.page.getByRole('heading', { name: '你好，visual_admin' }).waitFor(); await ctx.page.getByTestId('admin-invitations-link').click(); await ctx.page.getByTestId('create-invitation').waitFor();
      check(ctx.name, 'navigate away clears invitation without restoring or retrying', await ctx.page.getByTestId('invitation-code').count() === 0 && count(ctx, '/api/admin/invitations') === 2);
    }, { inviteDelay: 900 }, viewport);
  }
  for (const outcome of [403, 409, 429, 503, 'network', 'timeout', 'malformed-json', 'invalid-schema']) {
    await scenario(`admin-error-${outcome}`, 'admin', async (ctx) => {
      await ctx.page.goto(BASE + '/admin/invitations'); await ctx.page.getByTestId('create-invitation').click(); await ctx.page.getByRole('alert').first().waitFor();
      const uncertain = outcome === 503 || typeof outcome === 'string';
      check(ctx.name, 'error safe and no plaintext result', await ctx.page.getByTestId('invitation-code').count() === 0);
      check(ctx.name, 'uncertain result locks ordinary creation', await ctx.page.getByTestId('create-invitation').isDisabled() === uncertain);
      check(ctx.name, 'no automatic create retry', count(ctx, '/api/admin/invitations') === 1);
      if (uncertain) {
        ctx.page.once('dialog', (dialog) => dialog.dismiss()); await ctx.page.getByTestId('confirm-create-after-uncertain').click(); check(ctx.name, 'cancel acknowledgement sends no second create', count(ctx, '/api/admin/invitations') === 1);
      }
      await layout(ctx); await screenshot(ctx, ctx.name);
      if (uncertain) {
        ctx.state.inviteOutcome = 'success'; ctx.page.once('dialog', (dialog) => dialog.accept()); await ctx.page.getByTestId('confirm-create-after-uncertain').click(); await ctx.page.getByTestId('invitation-code').waitFor();
        check(ctx.name, 'explicit acknowledged retry only', count(ctx, '/api/admin/invitations') === 2);
      }
    }, { inviteOutcome: outcome }, viewports[2]);
  }
  await scenario('admin-session-expired', 'admin', async (ctx) => {
    await ctx.page.goto(BASE + '/admin/invitations'); await ctx.page.getByTestId('create-invitation').click(); await ctx.page.getByRole('alert').first().waitFor();
    check(ctx.name, '401 clears authenticated navigation', await ctx.page.getByTestId('admin-invitations-link').count() === 0 && await ctx.page.getByRole('link', { name: '登录', exact: true }).count() === 1);
    check(ctx.name, '401 removes protected create control or routes to login', new URL(ctx.page.url()).pathname === '/login' || await ctx.page.getByTestId('create-invitation').count() === 0 || await ctx.page.getByTestId('create-invitation').isDisabled());
    await screenshot(ctx, ctx.name);
  }, { inviteOutcome: 401 }, viewports[2]);
  await scenario('admin-pending-route-leave', 'admin', async (ctx) => {
    await ctx.page.goto(BASE + '/admin/invitations'); await ctx.page.getByTestId('create-invitation').click(); await ctx.page.getByText('正在创建…', { exact: true }).waitFor();
    await ctx.page.getByRole('link', { name: '首页', exact: true }).click(); await ctx.page.getByRole('heading', { name: '你好，visual_admin' }).waitFor();
    await ctx.page.waitForTimeout(850); await ctx.page.getByTestId('admin-invitations-link').click(); await ctx.page.getByTestId('create-invitation').waitFor();
    check(ctx.name, 'late success never restores unmounted plaintext', await ctx.page.getByTestId('invitation-code').count() === 0 && count(ctx, '/api/admin/invitations') === 1);
  }, { inviteDelay: 700 });
  await scenario('account-password-pending-and-logout', 'user', async (ctx) => {
    await ctx.page.goto(BASE + '/account'); await ctx.page.getByLabel('当前密码').fill(SYNTHETIC_PASSWORD); await ctx.page.getByLabel('新密码').fill(SYNTHETIC_PASSWORD);
    await ctx.page.locator('form').evaluate((form) => { form.requestSubmit(); form.requestSubmit(); }); await ctx.page.waitForTimeout(80);
    check(ctx.name, 'password change duplicate-submit protection', count(ctx, '/api/auth/change-password') === 1 && await ctx.page.locator('form button[type=submit]').isDisabled(), { requestCount: count(ctx, '/api/auth/change-password'), disabled: await ctx.page.locator('form button[type=submit]').isDisabled() });
    await screenshot(ctx, 'account-password-pending'); await ctx.page.getByText('密码修改失败，请检查输入后重试', { exact: true }).waitFor();
    check(ctx.name, 'password failure clears password inputs', await ctx.page.getByLabel('当前密码').inputValue() === '' && await ctx.page.getByLabel('新密码').inputValue() === '');
    ctx.state.logoutOutcome = 'error'; await ctx.page.getByTestId('logout').click(); await ctx.page.getByRole('alert').waitFor();
    check(ctx.name, 'uncertain logout preserves session with feedback', new URL(ctx.page.url()).pathname === '/account' && (await ctx.page.getByRole('alert').innerText()).includes('退出状态未确认')); await screenshot(ctx, 'account-logout-unconfirmed');
    ctx.state.logoutOutcome = 'success'; await ctx.page.getByTestId('logout').click(); await ctx.page.getByRole('heading', { name: '登录', exact: true }).waitFor();
    check(ctx.name, 'confirmed logout routes to login', new URL(ctx.page.url()).pathname === '/login');
  }, { passwordDelay: 800 }, viewports[2]);
  await scenario('account-session-unavailable', 'user', async (ctx) => {
    await ctx.page.goto(BASE + '/account'); await ctx.page.getByRole('heading', { name: '暂时无法确认登录状态' }).waitFor();
    check(ctx.name, 'unavailable Session hides password/logout controls', await ctx.page.getByTestId('logout').count() === 0 && await ctx.page.locator('input[type=password]').count() === 0); await screenshot(ctx, ctx.name);
  }, { sessionError: true }, viewports[2]);
}
