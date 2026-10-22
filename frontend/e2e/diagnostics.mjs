import { viewports } from './fixtures.mjs';

export async function runDiagnostics(qa) {
  const { BASE, scenario, check, layout, screenshot, tabs } = qa;
  for (const viewport of viewports) {
    await scenario(`personal-metrics-${viewport.name}`, 'user', async ctx => {
      await ctx.page.goto(BASE + '/');
      const overview = ctx.page.getByRole('region', { name: '我的预约概览', exact: true });
      await overview.getByText('2 小时 4 · 1 小时 2', { exact: true }).waitFor();
      check(ctx.name, 'personal metrics use only the personal API', ctx.state.requests.some(request => request.path === '/api/metrics/overview') && !ctx.state.requests.some(request => /^\/api\/admin\/(logs|metrics)/.test(request.path)));
      check(ctx.name, 'seven business dates expose readable numerical chart alternatives', await overview.locator('ol[aria-label="近七天执行任务状态"] > li[tabindex="0"]').count() === 7);
      check(ctx.name, 'ordinary users do not receive a runtime-log menu', await ctx.page.getByTestId('admin-logs-link').count() === 0);
      await layout(ctx); await screenshot(ctx, ctx.name);
      await ctx.page.goto(BASE + '/admin/logs');
      await ctx.page.getByRole('heading', { name: '你好，visual_user' }).waitFor();
      check(ctx.name, 'direct administrator route is blocked before reading logs', !ctx.state.requests.some(request => request.path.startsWith('/api/admin/logs')));
    }, {}, viewport);

    await scenario(`admin-logs-${viewport.name}`, 'admin', async ctx => {
      await ctx.page.goto(BASE + '/admin/logs');
      await ctx.page.getByRole('button', { name: '查看第 5 条日志详情', exact: true }).waitFor();
      check(ctx.name, 'admin log navigation is available', await ctx.page.getByTestId('admin-logs-link').count() === 1);
      await ctx.page.getByRole('button', { name: '查看第 5 条日志详情', exact: true }).click();
      await ctx.page.getByRole('heading', { name: '代码位置 · TimeoutError', exact: true }).waitFor();
      check(ctx.name, 'administrator can inspect source locations and related timeline', await ctx.page.getByRole('heading', { name: '关联事件时间线', exact: true }).count() === 1);
      await layout(ctx); await screenshot(ctx, ctx.name + '-detail');
      await ctx.page.getByLabel('日志级别', { exact: true }).selectOption('warning');
      await ctx.page.getByRole('button', { name: '查询日志', exact: true }).click();
      await ctx.page.locator('.runtime-event.level-warning').waitFor();
      check(ctx.name, 'filters refresh the list and close the previous detail', await ctx.page.locator('.runtime-event').count() === 1 && await ctx.page.getByRole('region', { name: '日志详情', exact: true }).count() === 0);
      await ctx.page.getByLabel('所属模块', { exact: true }).selectOption('agent');
      await ctx.page.getByRole('button', { name: '查询日志', exact: true }).click();
      await ctx.page.getByText('当前筛选范围内没有已采集的记录。', { exact: false }).waitFor();
      ctx.state.runtimeLogsError = true;
      await ctx.page.getByRole('button', { name: '刷新日志', exact: true }).click();
      await ctx.page.getByRole('alert').waitFor();
      check(ctx.name, 'a log-storage failure is distinguishable from an empty list and preserves login', new URL(ctx.page.url()).pathname === '/admin/logs' && (await ctx.page.getByRole('alert').innerText()).includes('日志暂时不可用'));
      await layout(ctx); await screenshot(ctx, ctx.name + '-unavailable');
      await ctx.page.getByRole('link', { name: '全站运行概览', exact: true }).click();
      await ctx.page.getByText('123 ms', { exact: true }).waitFor();
      check(ctx.name, 'administrator overview includes actual error trend and request metrics', await ctx.page.getByRole('heading', { name: '近七天异常趋势', exact: true }).count() === 1 && ctx.state.requests.some(request => request.path === '/api/admin/metrics'));
      if (viewport.width > 850) {
        const tops = await ctx.page.locator('.activity-charts > .activity-plot').evaluateAll(nodes => nodes.map(node => node.querySelector('.bar-track')?.getBoundingClientRect().top));
        check(ctx.name, 'desktop chart baselines align despite different header actions', tops.length === 2 && tops.every(top => typeof top === 'number') && Math.abs(tops[0] - tops[1]) <= 1, { tops });
      }
      await layout(ctx); await screenshot(ctx, ctx.name + '-metrics');
      await ctx.page.goto(BASE + '/admin/logs');
      await ctx.page.getByRole('heading', { name: '运行日志', exact: true }).waitFor();
      await tabs(ctx);
    }, {}, viewport);
  }
}
