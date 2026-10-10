import { SYNTHETIC_PASSWORD, credential, viewports } from './fixtures.mjs';

async function textGeometry(locator) {
  return locator.evaluateAll((elements) => elements.map((element) => {
    const rect = element.getBoundingClientRect();
    const walker = document.createTreeWalker(element, NodeFilter.SHOW_TEXT);
    const tops = new Set();
    while (walker.nextNode()) {
      if (!walker.currentNode.textContent.trim()) continue;
      const range = document.createRange();
      range.selectNodeContents(walker.currentNode);
      for (const line of range.getClientRects()) if (line.width > 0) tops.add(Math.round(line.top));
    }
    return { text: element.textContent.trim(), lines: tops.size, width: rect.width, height: rect.height, left: rect.left, right: rect.right };
  }));
}

export async function runRegressions(qa) {
  const { BASE, scenario, check, screenshot, layout, tabs, waitCredentials, count } = qa;
  const mainLinks = async (ctx) => {
    const links = await textGeometry(ctx.page.locator('main a'));
    check(ctx.name, 'F7 visible action links have usable touch targets', links.every((link) => link.width >= 44 && link.height >= 44 && link.lines === 1), { links });
  };
  for (const viewport of viewports) {
    for (const [route, label, target] of [['/login', '使用邀请码注册', '/register'], ['/register', '返回登录', '/login']]) {
      await scenario(`regression-inline-links-${route.slice(1)}-${viewport.name}`, 'anonymous', async (ctx) => {
        await ctx.page.goto(BASE + route);
        const link = ctx.page.getByRole('link', { name: label, exact: true });
        await link.waitFor();
        await mainLinks(ctx);
        await layout(ctx);
        await tabs(ctx);
        await screenshot(ctx, ctx.name);
        await link.click();
        check(ctx.name, 'F7 action link reaches its route', new URL(ctx.page.url()).pathname === target);
      }, {}, viewport);
    }
    for (const role of ['user', 'admin']) {
      await scenario(`regression-navigation-${role}-${viewport.name}`, role, async (ctx) => {
        await ctx.page.goto(BASE + '/');
        await ctx.page.getByRole('heading', { name: `你好，visual_${role}` }).waitFor();
        const links = [['首页', '/'], ['预约凭据', '/credentials'], ...(role === 'admin' ? [['邀请码管理', '/admin/invitations']] : []), ['账户', '/account']];
        for (const [label, route] of links) {
          const link = ctx.page.getByRole('navigation', { name: '主导航' }).getByRole('link', { name: label, exact: true });
          await link.click();
          check(ctx.name, `F1 click ${label} reaches its route`, new URL(ctx.page.url()).pathname === route && await link.isVisible());
          const nav = await textGeometry(ctx.page.locator('.topbar a'));
          check(ctx.name, `F1 complete labels on ${route}`, nav.every((n) => n.lines === 1), { nav });
          check(ctx.name, `F7 navigation touch targets on ${route}`, nav.every((n) => n.width >= 44 && n.height >= 44), { nav });
          await mainLinks(ctx);
          await layout(ctx);
        }
        await ctx.page.locator('.brand').click();
        await ctx.page.getByRole('heading', { name: `你好，visual_${role}` }).waitFor();
        const management = ctx.page.getByRole('link', { name: '管理凭据', exact: true });
        const geometry = await textGeometry(management);
        check(ctx.name, 'F6 home link is complete and touchable', geometry[0].lines === 1 && geometry[0].width >= 44 && geometry[0].height >= 44, { geometry });
        await tabs(ctx);
        await screenshot(ctx, ctx.name);
        await management.click();
        await waitCredentials(ctx.page);
        check(ctx.name, 'F6 home link reaches credentials', new URL(ctx.page.url()).pathname === '/credentials');
        const refresh = ctx.page.locator('.section-heading button');
        await refresh.click();
        await waitCredentials(ctx.page);
        const controls = await textGeometry(ctx.page.locator('.credential-actions button, .text-button'));
        check(ctx.name, 'F7 Credential action/refresh touch targets', controls.every((c) => c.height >= 44 && c.width >= 44), { controls });
      }, {}, viewport);
    }
    await scenario(`regression-long-name-${viewport.name}`, 'user', async (ctx) => {
      await ctx.page.goto(BASE + '/credentials');
      await waitCredentials(ctx.page);
      const title = ctx.page.locator('.credential-card h3');
      check(ctx.name, 'F2 full 128-character label preserved', await title.innerText() === 'W'.repeat(128));
      const geometry = await layout(ctx);
      check(ctx.name, 'F2 title, status, inputs and controls remain within viewport', geometry.overflowing.length === 0, { overflowing: geometry.overflowing });
      await screenshot(ctx, ctx.name);
    }, { credentials: [credential('visual-confirmed', 'W'.repeat(128))] }, viewport);
  }

  await scenario('regression-admin-401-no-second-create', 'admin', async (ctx) => {
    await ctx.page.goto(BASE + '/admin/invitations');
    await ctx.page.getByTestId('create-invitation').click();
    await ctx.page.getByText('登录状态已失效，请重新登录后再试。', { exact: false }).waitFor();
    const button = ctx.page.getByTestId('create-invitation');
    check(ctx.name, 'F3 Session loss disables the creation button', await button.isDisabled());
    const box = await button.boundingBox();
    await ctx.page.mouse.click(box.x + box.width / 2, box.y + box.height / 2);
    await ctx.page.keyboard.press('Enter');
    // Bypass native disabled semantics to exercise the handler's own permission guard.
    await ctx.page.locator('form').evaluate((form) => form.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true })));
    await ctx.page.waitForTimeout(100);
    check(ctx.name, 'F3 guarded handler never sends a second POST', count(ctx, '/api/admin/invitations') === 1);
    check(ctx.name, 'F3 no plaintext and visible login feedback', await ctx.page.getByTestId('invitation-code').count() === 0 && await ctx.page.getByRole('link', { name: '重新登录', exact: true }).count() === 1);
    await mainLinks(ctx);
    await screenshot(ctx, ctx.name);
  }, { inviteOutcome: 401 }, viewports[2]);

  await scenario('regression-admin-500-acknowledgement', 'admin', async (ctx) => {
    await ctx.page.goto(BASE + '/admin/invitations');
    await ctx.page.getByTestId('create-invitation').click();
    await ctx.page.getByText('创建结果尚未确认', { exact: false }).waitFor();
    check(ctx.name, 'F3 uncertain 500 disables ordinary creation', await ctx.page.getByTestId('create-invitation').isDisabled());
    ctx.page.once('dialog', (dialog) => dialog.dismiss());
    await ctx.page.getByTestId('confirm-create-after-uncertain').click();
    check(ctx.name, 'F3 no retry after cancel', count(ctx, '/api/admin/invitations') === 1);
    await screenshot(ctx, ctx.name);
    ctx.state.inviteOutcome = 'success';
    ctx.page.once('dialog', (dialog) => dialog.accept());
    await ctx.page.getByTestId('confirm-create-after-uncertain').click();
    await ctx.page.getByTestId('invitation-code').waitFor();
    check(ctx.name, 'F3 second creation requires explicit acknowledgement', count(ctx, '/api/admin/invitations') === 2);
  }, { inviteOutcome: 500 }, viewports[2]);

  for (const outcome of ['error', 'success']) {
    await scenario(`regression-password-${outcome}`, 'user', async (ctx) => {
      await ctx.page.goto(BASE + '/account');
      await ctx.page.getByLabel('当前密码').fill(SYNTHETIC_PASSWORD);
      await ctx.page.getByLabel('新密码').fill(SYNTHETIC_PASSWORD);
      await ctx.page.locator('form button[type=submit]').click();
      await ctx.page.keyboard.press('Enter');
      await ctx.page.locator('form').evaluate((form) => { form.requestSubmit(); form.requestSubmit(); });
      await ctx.page.waitForTimeout(100);
      check(ctx.name, 'F4 mouse/Enter/repeated form submits send one POST', count(ctx, '/api/auth/change-password') === 1);
      check(ctx.name, 'F4 disabled submit and visible pending feedback', await ctx.page.locator('form button[type=submit]').isDisabled() && await ctx.page.getByText('正在修改密码…', { exact: true }).count() === 1);
      await screenshot(ctx, `${ctx.name}-pending`);
      if (outcome === 'error') {
        await ctx.page.getByText('密码修改失败，请检查输入后重试', { exact: true }).waitFor();
        check(ctx.name, 'F4 failure unlocks submit and clears password inputs', !await ctx.page.locator('form button[type=submit]').isDisabled() && await ctx.page.getByLabel('当前密码').inputValue() === '' && await ctx.page.getByLabel('新密码').inputValue() === '');
      } else {
        await ctx.page.getByText('密码已修改，请重新登录。', { exact: true }).waitFor();
        check(ctx.name, 'F4 success clears inputs and prevents a new authenticated submission', await ctx.page.locator('input[type=password]').count() === 0 && await ctx.page.getByRole('link', { name: '重新登录', exact: true }).count() === 1);
        await mainLinks(ctx);
      }
      await layout(ctx);
      await screenshot(ctx, `${ctx.name}-settled`);
    }, { passwordDelay: 800, passwordOutcome: outcome }, viewports[2]);
  }

  for (const failure of ['503', 'network']) {
    await scenario(`regression-credential-${failure}-retry`, 'user', async (ctx) => {
      await ctx.page.goto(BASE + '/credentials');
      await ctx.page.getByRole('alert').waitFor();
      check(ctx.name, 'F5 failure and success-empty are mutually exclusive', await ctx.page.locator('.empty-state').count() === 0);
      await screenshot(ctx, `${ctx.name}-error`);
      ctx.state.listError = false;
      ctx.state.listNetworkError = false;
      ctx.state.credentials = failure === '503' ? [] : [credential('visual-confirmed', '合成凭据 · 已确认')];
      ctx.state.listDelay = 500;
      await ctx.page.getByRole('button', { name: '重试', exact: true }).click();
      await ctx.page.getByText('正在读取凭据状态…', { exact: true }).waitFor();
      check(ctx.name, 'F5 pending retry is a loading state, not empty/error', await ctx.page.getByRole('alert').count() === 0 && await ctx.page.locator('.empty-state').count() === 0);
      await screenshot(ctx, `${ctx.name}-loading`);
      if (failure === '503') await ctx.page.locator('.empty-state').waitFor();
      else await waitCredentials(ctx.page);
      check(ctx.name, 'F5 successful retry reports the actual list', await ctx.page.getByRole('alert').count() === 0 && count(ctx, '/api/credentials', 'GET') === 2 && await ctx.page.locator('.empty-state').count() === (failure === '503' ? 1 : 0));
      await layout(ctx);
      await screenshot(ctx, `${ctx.name}-success`);
    }, { listError: failure === '503', listNetworkError: failure === 'network' }, viewports[2]);
  }
  await scenario('regression-credential-stale-refresh', 'user', async (ctx) => {
    await ctx.page.goto(BASE + '/credentials');
    await waitCredentials(ctx.page);
    ctx.state.listError = true;
    await ctx.page.locator('.section-heading button').click();
    await ctx.page.getByRole('alert').waitFor();
    check(ctx.name, 'F5 failed refresh hides stale list and does not claim empty', await ctx.page.locator('.credential-card').count() === 0 && await ctx.page.locator('.empty-state').count() === 0);
    await screenshot(ctx, ctx.name);
  }, {}, viewports[2]);
}
