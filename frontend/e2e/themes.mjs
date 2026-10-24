import { fixtures, viewports, SYNTHETIC_CODE, SYNTHETIC_PASSWORD } from './fixtures.mjs';

const readyCredentials = fixtures.map(item => ({ ...item, has_payment_password: true }));

async function readable(qa, ctx, label, selector) {
  const samples = await ctx.page.locator(selector).evaluateAll(nodes => {
    const rgba = value => (value.match(/[\d.]+/g) || []).map(Number);
    const over = (front, back) => front.slice(0, 3).map((value, index) => value * (front[3] ?? 1) + back[index] * (1 - (front[3] ?? 1)));
    const luminance = rgb => rgb.map(value => value / 255).map(value => value <= .04045 ? value / 12.92 : ((value + .055) / 1.055) ** 2.4).reduce((sum, value, index) => sum + value * [.2126, .7152, .0722][index], 0);
    return nodes.filter(node => node.getClientRects().length && !node.closest(':disabled')).map(node => {
      const ancestors = [];
      for (let current = node; current; current = current.parentElement) ancestors.unshift(current);
      const background = ancestors.reduce((back, element) => over(rgba(getComputedStyle(element).backgroundColor), back), [255, 255, 255]);
      const style = getComputedStyle(node);
      const a = luminance(over(rgba(style.color), background)), b = luminance(background);
      return { class: node.className, foreground: style.color, background, contrast: (Math.max(a, b) + .05) / (Math.min(a, b) + .05) };
    });
  });
  qa.check(ctx.name, label + ' text contrast ≥ 4.5:1', samples.length > 0 && samples.every(sample => sample.contrast >= 4.5), { samples });
}

async function theme(qa, ctx, scheme) {
  const actual = await ctx.page.evaluate(() => ({
    scheme: getComputedStyle(document.documentElement).colorScheme,
    page: getComputedStyle(document.body).backgroundColor,
    surface: getComputedStyle(document.documentElement).getPropertyValue('--surface').trim(),
    toolbar: getComputedStyle(document.querySelector('.topbar')).backgroundColor,
    browserTheme: [...document.querySelectorAll('meta[name="theme-color"]')].filter(meta => matchMedia(meta.media).matches).map(meta => meta.content),
  }));
  qa.check(ctx.name, 'system preference reaches the canvas, cards, navigation and browser chrome', actual.scheme === scheme
    && actual.page === (scheme === 'dark' ? 'rgb(0, 0, 0)' : 'rgb(245, 245, 247)')
    && actual.surface === (scheme === 'dark' ? '#161617' : '#ffffff')
    && actual.toolbar === (scheme === 'dark' ? 'rgba(22, 22, 23, 0.82)' : 'rgba(255, 255, 255, 0.78)')
    && actual.browserTheme.join() === (scheme === 'dark' ? '#000000' : '#f5f5f7'), actual);
  await readable(qa, ctx, 'page headings and secondary copy', 'main h1, main h2, main .muted');
  await qa.layout(ctx);
}

async function mockGrid(page) {
  await page.route('**/api/availability/live/grid', route => {
    const now = Date.now();
    const states = [
      { state: 'observed_clear_unmarked' }, { state: 'observed_reserved' },
      { state: 'observed_unbookable' }, { state: 'observed_unknown' },
      ...Array.from({ length: 7 }, (_, activity_type) => ({ state: 'observed_activity_occupied', activity_type })),
    ];
    return route.fulfill({ json: {
      grid_version: 'official-bookingByTime-live-observation-v1', data_state: 'live_observed_unverified', simulation: false,
      target_date: route.request().postDataJSON().target_date, timezone_name: 'Asia/Shanghai',
      query_scope: { display_name: '羽毛球', physical_venue_verified: false },
      can_select: false, can_select_intent: false, can_match: false, can_bind: false, can_book: false, can_pay: false, can_create_job: false,
      client_selection_window: 'open',
      source: { data_state: 'live_observed_unverified', trust_state: 'display_only_unverified', price_state: 'displayed_unit_unverified', captured_at_utc_ms: now, ui_stale_after_utc_ms: now + 60000 },
      courts: Array.from({ length: 10 }, (_, index) => ({ display_name: `${index + 1}号场` })),
      rows: Array.from({ length: 2 }, (_, row) => ({ time_label: `${row + 9}:00`, time_status_code: '0', cells: Array.from({ length: 10 }, (_, col) => ({ ...states[(row * 10 + col) % states.length], price_display: '20', selectable: false, intent_selectable: false })) })),
    } });
  });
}

export async function runThemes(qa) {
  const { BASE, scenario, screenshot, check } = qa;
  for (const scheme of ['light', 'dark']) for (const viewport of [viewports[0], viewports[2]]) {
    await scenario(`theme-public-${scheme}-${viewport.name}`, 'anonymous', async ctx => {
      await ctx.page.emulateMedia({ colorScheme: scheme });
      await ctx.page.goto(BASE + '/login');
      await ctx.page.getByRole('heading', { name: '登录', exact: true }).waitFor();
      await theme(qa, ctx, scheme);
      await readable(qa, ctx, 'login card, inputs and main action', '.auth-card, .field input, .primary-button');
      const input = ctx.page.getByLabel('用户名');
      await input.fill('theme-draft');
      const requests = ctx.state.requests.length;
      const other = scheme === 'dark' ? 'light' : 'dark';
      await ctx.page.emulateMedia({ colorScheme: other });
      await ctx.page.waitForFunction(expected => getComputedStyle(document.documentElement).colorScheme === expected, other);
      check(ctx.name, 'a live system-theme change preserves the form without reloads or API calls', await input.inputValue() === 'theme-draft' && requests === ctx.state.requests.length);
      await theme(qa, ctx, other);
      await ctx.page.emulateMedia({ colorScheme: scheme });
      await ctx.page.waitForFunction(expected => getComputedStyle(document.documentElement).colorScheme === expected, scheme);
      await input.focus();
      const focus = await input.evaluate(node => ({ scheme: getComputedStyle(node).colorScheme, ring: getComputedStyle(node).boxShadow }));
      check(ctx.name, 'native inputs inherit the theme and keep a focus ring', focus.scheme === scheme && focus.ring !== 'none', focus);
      await screenshot(ctx, ctx.name + '-login');
      ctx.state.loginOutcome = 'error';
      await ctx.page.getByLabel('密码', { exact: true }).fill(SYNTHETIC_PASSWORD);
      await ctx.page.getByRole('button', { name: '登录', exact: true }).click();
      await ctx.page.getByRole('alert').waitFor();
      await readable(qa, ctx, 'validation feedback', '.form-error');
      await ctx.page.goto(BASE + '/register');
      await ctx.page.getByRole('heading', { name: '邀请码注册', exact: true }).waitFor();
      await theme(qa, ctx, scheme);
      await readable(qa, ctx, 'registration form', '.field input, .primary-button');
      await ctx.page.getByTestId('invite-code').fill(SYNTHETIC_CODE);
      await ctx.page.getByTestId('username').fill('visual_user');
      await ctx.page.getByTestId('password').fill(SYNTHETIC_PASSWORD);
      await ctx.page.getByRole('button', { name: '创建账户' }).click();
      await ctx.page.getByRole('status').waitFor();
      await readable(qa, ctx, 'successful form feedback', '.form-success, .success-message');
      await screenshot(ctx, ctx.name + '-register');
    }, {}, viewport);

    await scenario(`theme-workspace-${scheme}-${viewport.name}`, 'admin', async ctx => {
      await ctx.page.emulateMedia({ colorScheme: scheme });
      await mockGrid(ctx.page);
      for (const [slug, route, ready] of [
        ['home', '/', '.activity-overview'],
        ['credentials', '/credentials', '[data-testid="credential-card-visual-confirmed"]'],
        ['account', '/account', '[data-testid="logout"]'],
        ['models', '/settings/ai-models', '.model-row'],
        ['users', '/admin', '.admin-user-table'],
        ['logs', '/admin/logs', '.runtime-event'],
        ['invitations', '/admin/invitations', '[data-testid="create-invitation"]'],
        ['query', '/plans', '[data-testid="live-availability-grid"]'],
      ]) {
        await ctx.page.goto(BASE + route);
        await ctx.page.locator(ready).first().waitFor();
        if (slug === 'home') await ctx.page.getByText('2 小时 4 · 1 小时 2', { exact: true }).waitFor();
        if (slug === 'credentials') {
          await ctx.page.locator('.credential-add > summary').click();
          await readable(qa, ctx, 'credential states and forms', '.credential-card, .credential-card .state-pill, .credential-create-grid input, .credential-create-grid .primary-button');
          const danger = ctx.page.getByTestId('credential-delete-visual-confirmed');
          await danger.hover();
          await readable(qa, ctx, 'danger action on hover', '[data-testid="credential-delete-visual-confirmed"]');
        }
        if (slug === 'account') await readable(qa, ctx, 'account primary and secondary actions', '.primary-button, .secondary-button, .field input');
        if (slug === 'models') {
          await ctx.page.locator('.model-row').first().getByRole('button', { name: '编辑', exact: true }).click();
          await ctx.page.locator('.model-editor').waitFor();
          await readable(qa, ctx, 'model editor', '.model-editor input');
          await screenshot(ctx, ctx.name + '-models-editor');
          await ctx.page.locator('.model-editor').getByRole('button', { name: '取消', exact: true }).click();
          await ctx.page.locator('details.model-presets > summary').click();
          await ctx.page.locator('.model-quick-guide > summary').click();
          await readable(qa, ctx, 'configuration popover', '.model-quick-guide > div');
        }
        if (slug === 'logs') {
          await ctx.page.getByRole('button', { name: '查看第 5 条日志详情', exact: true }).click();
          await ctx.page.getByRole('heading', { name: '代码位置 · TimeoutError', exact: true }).waitFor();
          await readable(qa, ctx, 'log detail and severity text', '.log-detail, .runtime-event.level-warning');
        }
        if (slug === 'invitations') {
          await ctx.page.getByTestId('create-invitation').click();
          await ctx.page.getByTestId('invitation-code').waitFor();
          await readable(qa, ctx, 'invitation code and result card', '.invitation-result, .invitation-code');
        }
        if (slug === 'query') {
          const palette = await ctx.page.locator('.observation-cell').evaluateAll(nodes => nodes.map(node => ({ color: getComputedStyle(node).color, background: getComputedStyle(node).backgroundColor, unknown: node.classList.contains('cell-observed_unknown'), classes: node.className })));
          check(ctx.name, 'official colored cells keep dark price text in both themes', palette.length === 20 && palette.filter(item => !item.unknown).every(item => item.color === 'rgb(29, 29, 31)'), { palette });
          check(ctx.name, 'official clear/reserved/activity colors are preserved', palette.some(item => item.background === 'rgb(255, 255, 255)') && palette.some(item => item.background === 'rgb(7, 98, 199)') && palette.some(item => item.background === 'rgb(255, 232, 163)'), { palette });
          await readable(qa, ctx, 'selected date', '.date-strip-options > button[aria-pressed="true"]');
        }
        await theme(qa, ctx, scheme);
        await screenshot(ctx, ctx.name + '-' + slug, { fullPage: slug !== 'credentials' });
      }
      for (const tab of ['manual', 'agent', 'current', 'orders']) {
        await ctx.page.getByTestId('plan-tab-' + tab).click();
        if (tab === 'manual') {
          await ctx.page.locator('.duration-segment').waitFor();
          await readable(qa, ctx, 'selected duration', '.duration-segment button[aria-pressed="true"]');
        }
        if (tab === 'agent') {
          await ctx.page.locator('.proposal-chat textarea').waitFor();
          await ctx.page.locator('.queue-preview-details > summary').click();
          await readable(qa, ctx, 'Agent composer and queue preview', '.proposal-chat textarea, .queue-preview');
        }
        if (tab === 'current') {
          await ctx.page.locator('.execution-settings-disclosure > summary').click();
          await ctx.page.locator('.execution-settings-form').waitFor();
          await ctx.page.getByLabel('查看执行时间和延迟说明').focus();
          await ctx.page.getByRole('tooltip').waitFor();
          await readable(qa, ctx, 'execution form and tooltip', '.execution-settings-form input, [role="tooltip"]');
        }
        if (tab === 'orders') {
          await ctx.page.locator('.order-query-panel').waitFor();
          await readable(qa, ctx, 'order filter and actions', '.order-query-panel select, .order-query-panel .primary-button');
        }
        await theme(qa, ctx, scheme);
        await screenshot(ctx, ctx.name + '-' + tab);
      }
    }, { credentials: readyCredentials, liveEnabled: true }, viewport);
  }
}
