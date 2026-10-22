import { fixtures, viewports } from './fixtures.mjs';
import { logFixture, logsFixture } from '../test-support/diagnostics.js';

const readyCredentials = fixtures.map(item => ({ ...item, has_payment_password: true }));
const widths = [
  ...viewports,
  { name: 'small-phone', width: 320, height: 740 },
  { name: 'help-breakpoint', width: 600, height: 900 },
  { name: 'desktop-breakpoint', width: 1025, height: 768 },
  { name: 'short-laptop', width: 1280, height: 600 },
  { name: 'wide-desktop', width: 1920, height: 1080 },
];

export async function runResponsive(qa) {
  const { BASE, scenario, check, screenshot, layout } = qa;
  for (const viewport of widths) {
    await scenario(`responsive-assistant-${viewport.name}`, 'admin', async ctx => {
      await ctx.page.goto(BASE + '/plans?tab=agent');
      const chat = ctx.page.locator('.proposal-chat');
      await chat.locator('.queue-preview').waitFor();
      const geometry = await chat.evaluate(node => {
        const box = selector => {
          const rect = node.querySelector(selector).getBoundingClientRect();
          return { top: rect.top, bottom: rect.bottom, left: rect.left, right: rect.right, width: rect.width };
        };
        return { preview: box('.queue-preview'), messages: box('.proposal-chat-messages'), input: box('textarea'), control: box('.plan-credential-control') };
      });
      check(ctx.name, 'the visible Agent preview is above messages on narrow layouts', viewport.width > 1024 || geometry.preview.bottom <= geometry.messages.top + 1, geometry);
      check(ctx.name, 'phone composer is usable in the first viewport', viewport.width > 600 || geometry.input.bottom <= viewport.height, geometry);
      check(ctx.name, 'credential controls fit within the viewport', geometry.control.left >= 0 && geometry.control.right <= viewport.width, geometry);
      await chat.getByText('示例与说明', { exact: true }).click();
      check(ctx.name, 'welcome examples remain available on demand', await chat.locator('.chat-welcome-help .chat-example').isVisible());
      await chat.getByText('示例与说明', { exact: true }).click();
      await chat.locator('.queue-preview-details > summary').click();
      check(ctx.name, 'one and two hour groups remain separate and readable', await chat.getByRole('region', { name: '2小时队列', exact: true }).isVisible() && await chat.getByRole('region', { name: '1小时队列', exact: true }).isVisible());
      await chat.locator('.queue-preview-details > summary').click();
      await layout(ctx); await screenshot(ctx, ctx.name);

      if (viewport.width === 390) {
        const beforeY = await ctx.page.evaluate(() => scrollY);
        await ctx.page.setViewportSize({ width:320, height:740 });
        await ctx.page.waitForFunction(() => {
          return ['.topbar nav', '.plan-section-tabs'].every(selector => {
            const nav = document.querySelector(selector), active = nav.querySelector('.router-link-exact-active, [aria-selected="true"]');
            const n = nav.getBoundingClientRect(), a = active.getBoundingClientRect();
            return a.left >= n.left - 1 && a.right <= n.right + 1;
          });
        });
        check(ctx.name, 'resizing keeps both active navigation items visible without moving the page vertically', Math.abs(await ctx.page.evaluate(() => scrollY) - beforeY) <= 1);
        await ctx.page.setViewportSize({ width:viewport.width, height:viewport.height });
      }

      await ctx.page.getByTestId('plan-tab-current').click();
      await ctx.page.locator('.execution-settings-form').waitFor();
      await ctx.page.getByLabel('查看执行时间和延迟说明').focus();
      const help = ctx.page.getByRole('tooltip');
      await help.waitFor();
      const box = await help.boundingBox();
      check(ctx.name, 'execution help stays fully inside the viewport', box.x >= 0 && box.x + box.width <= viewport.width + 1 && box.y >= 0 && box.y + box.height <= viewport.height + 1, { box, viewport });
      await layout(ctx); await screenshot(ctx, ctx.name + '-help');
    }, { credentials: readyCredentials }, viewport);
  }

  for (const viewport of [widths[0], widths[2], widths[5]]) {
    await scenario(`responsive-inline-details-${viewport.name}`, 'admin', async ctx => {
      await ctx.page.route('**/api/admin/logs?*', route => route.fulfill({
        status: 200, contentType: 'application/json', body: JSON.stringify({ ...logsFixture(), events: Array.from({ length: 50 }, (_, index) => logFixture(100 - index)) }),
      }));
      await ctx.page.route('**/api/admin/logs/100', route => route.fulfill({ status:200, contentType:'application/json', body:JSON.stringify({ event:logFixture(100), related:[], related_truncated:false }) }));
      await ctx.page.goto(BASE + '/admin/logs');
      const first = ctx.page.locator('.runtime-event').first();
      await first.getByRole('button', { name: '查看第 100 条日志详情', exact: true }).click();
      await first.getByRole('region', { name: '日志详情', exact: true }).waitFor();
      const distance = await first.evaluate(node => {
        const button = node.querySelector('button').getBoundingClientRect();
        const detail = node.querySelector('.log-detail').getBoundingClientRect();
        return { gap: detail.top - button.bottom };
      });
      check(ctx.name, 'details open beside the chosen event with a dense list', distance.gap >= 0 && distance.gap <= 32, distance);
      const nav = await ctx.page.locator('.topbar nav').evaluate(node => {
        const rect = node.getBoundingClientRect(), active = node.querySelector('.router-link-exact-active').getBoundingClientRect();
        return { left: rect.left, right: rect.right, activeLeft: active.left, activeRight: active.right };
      });
      check(ctx.name, 'the current global navigation item is visible', nav.activeLeft >= nav.left - 1 && nav.activeRight <= nav.right + 1, nav);
      await layout(ctx); await screenshot(ctx, ctx.name + '-log', { fullPage:false });

      await ctx.page.route('**/api/ai/models', route => route.fulfill({
        status: 200, contentType: 'application/json', body: JSON.stringify({
          models: Array.from({ length: 3 }, (_, index) => ({ id: `visual-model-${index}`, name: `合成模型${index + 1}`, model: 'deepseek-chat', version: 1, base_url: 'https://example.invalid/v1', auth_mode: 'bearer', has_api_key: true })),
          selected_model_id: 'visual-model-0', effective_model_id: 'visual-model-0', default_model_id: 'visual-model-0', service_default: null,
        }),
      }));
      await ctx.page.goto(BASE + '/settings/ai-models');
      const model = ctx.page.locator('.model-row').first();
      await model.getByRole('button', { name: '编辑', exact: true }).click();
      await model.locator('.model-editor').waitFor();
      check(ctx.name, 'the editor belongs to the chosen model instead of the list footer', await ctx.page.locator('.model-row:nth-child(2) .model-editor').count() === 0 && await ctx.page.locator('.model-editor').count() === 1);
      await layout(ctx); await screenshot(ctx, ctx.name + '-model', { fullPage:false });
      if (viewport.width === 390) {
        await ctx.page.setViewportSize({ width:768, height:1024 });
        await ctx.page.waitForFunction(() => {
          const nav = document.querySelector('.topbar nav'), active = nav.querySelector('.router-link-exact-active');
          const n = nav.getBoundingClientRect(), a = active.getBoundingClientRect();
          return a.left >= n.left - 1 && a.right <= n.right + 1;
        });
        await ctx.page.setViewportSize({ width:320, height:740 });
        await ctx.page.waitForFunction(() => {
          const nav = document.querySelector('.topbar nav'), active = nav.querySelector('.router-link-exact-active');
          const n = nav.getBoundingClientRect(), a = active.getBoundingClientRect();
          return a.left >= n.left - 1 && a.right <= n.right + 1;
        });
        check(ctx.name, 'the last global navigation item stays visible when shrinking a tablet to a phone', await ctx.page.locator('.topbar nav .router-link-exact-active').innerText() === '设置 · AI模型');
      }

    }, { credentials: readyCredentials }, viewport);
  }
}
