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
      await ctx.page.locator('.execution-settings-disclosure > summary').click();
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
      await first.waitFor();
      const firstLog = await first.boundingBox();
      check(ctx.name, 'log results begin in the first viewport', firstLog.y < viewport.height, { firstLog });
      await first.getByRole('button', { name: '查看第 100 条日志详情', exact: true }).click();
      await first.getByRole('region', { name: '日志详情', exact: true }).waitFor();
      const distance = await first.evaluate(node => {
        const button = node.querySelector('button').getBoundingClientRect();
        const detail = node.querySelector('.log-detail').getBoundingClientRect();
        return { gap: detail.top - button.bottom };
      });
      check(ctx.name, 'details open beside the chosen event with a dense list', distance.gap >= 0 && distance.gap <= 32, distance);
      const nav = await ctx.page.locator('.topbar nav').evaluate(node => {
        const rect = node.getBoundingClientRect(), active = node.querySelector('.nav-group.is-active > summary, .router-link-exact-active').getBoundingClientRect();
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
      check(ctx.name, 'editing focuses one model and hides preference controls', await ctx.page.locator('.model-row:visible').count() === 1 && !await ctx.page.locator('.preference-save').isVisible());
      await layout(ctx); await screenshot(ctx, ctx.name + '-model', { fullPage:false });
      if (viewport.width === 390) {
        await ctx.page.setViewportSize({ width:768, height:1024 });
        await ctx.page.waitForFunction(() => {
          const nav = document.querySelector('.topbar nav'), active = nav.querySelector('.nav-group.is-active > summary, .router-link-exact-active');
          const n = nav.getBoundingClientRect(), a = active.getBoundingClientRect();
          return a.left >= n.left - 1 && a.right <= n.right + 1;
        });
        await ctx.page.setViewportSize({ width:320, height:740 });
        await ctx.page.waitForFunction(() => {
          const nav = document.querySelector('.topbar nav'), active = nav.querySelector('.nav-group.is-active > summary, .router-link-exact-active');
          const n = nav.getBoundingClientRect(), a = active.getBoundingClientRect();
          return a.left >= n.left - 1 && a.right <= n.right + 1;
        });
        check(ctx.name, 'the last global navigation item stays visible when shrinking a tablet to a phone', await ctx.page.locator('.topbar nav .nav-group.is-active > summary').isVisible() && (await ctx.page.locator('.topbar nav .router-link-exact-active').textContent()).trim() === '设置 · AI模型');
      }
      await model.locator('.model-editor').getByRole('button', { name: '取消', exact: true }).click();
      check(ctx.name, 'cancel restores model choices without a configuration write', await ctx.page.locator('.model-row:visible').count() === 3 && await ctx.page.locator('.preference-save').isVisible() && !ctx.state.requests.some(request => request.path === '/api/ai/models' && request.method !== 'GET'));
    }, { credentials: readyCredentials }, viewport);
  }

  for (const viewport of [viewports[0], viewports[2]]) {
    await scenario(`responsive-loaded-grids-${viewport.name}`, 'admin', async ctx => {
      await ctx.page.route('**/api/plans/manual-queues/*', route => {
        if (route.request().method() !== 'PUT') return route.fallback();
        const body = route.request().postDataJSON();
        return route.fulfill({ json: { queue: {
          credential_id: body.credential_id, target_date: new URL(route.request().url()).pathname.split('/').at(-1), version: body.base_version + 1,
          candidates: body.entries.map(entry => ({ duration_minutes: entry.duration_minutes, preferred_start_times: [entry.start_time], court_preferences: [entry.court_preference], query_scope_label: entry.scope_label })),
        } } });
      });
      await ctx.page.route('**/api/availability/live/options', route => route.fulfill({ json: { enabled: true, min_read_interval_ms: 10 } }));
      await ctx.page.route('**/api/availability/live/categories', route => route.fulfill({ json: {
        data_state: 'live_observed_unverified', source: 'official_read_only',
        options: [{ reference: 'synthetic-badminton', label: '羽毛球', physical_venue_verified: false }],
      } }));
      await ctx.page.route('**/api/availability/live/grid', route => {
        const targetDate = route.request().postDataJSON().target_date;
        const states = ['observed_clear_unmarked', 'observed_reserved', 'observed_activity_occupied', 'observed_unbookable', 'observed_unknown'];
        return route.fulfill({ json: {
          grid_version: 'official-bookingByTime-live-observation-v1', data_state: 'live_observed_unverified', simulation: false,
          target_date: targetDate, timezone_name: 'Asia/Shanghai', query_scope: { display_name: '羽毛球', physical_venue_verified: false },
          can_select: false, can_select_intent: true, can_match: false, can_bind: false, can_book: false, can_pay: false, can_create_job: false, client_selection_window: 'open',
          source: { data_state: 'live_observed_unverified', trust_state: 'display_only_unverified', price_state: 'displayed_unit_unverified', captured_at_utc_ms: Date.now(), ui_stale_after_utc_ms: Date.now() + 60000 },
          courts: Array.from({ length: 10 }, (_, index) => ({ display_name: `${index + 1}号场` })),
          rows: Array.from({ length: 13 }, (_, index) => ({
            time_label: `${String(index + 9).padStart(2, '0')}:00`, time_status_code: '0', intent_start_time: `${String(index + 9).padStart(2, '0')}:00`, intent_end_time: `${index + 10}:00`,
            cells: Array.from({ length: 10 }, (_, court) => ({ state: states[(index + court) % states.length], activity_type: (index + court) % 7, price_display: '20', selectable: false, intent_selectable: false })),
          })), notice: '合成视觉测试数据，不代表真实场地。',
        } });
      });
      await ctx.page.goto(BASE + '/plans');
      await ctx.page.getByTestId('live-availability-grid').waitFor();
      check(ctx.name, 'loaded observation grid retains all ten courts and prices', await ctx.page.locator('.observation-table thead th').count() === 11 && await ctx.page.locator('.observation-price').count() === 130);
      const gridBounds = await ctx.page.locator('.observation-scroll').evaluate(node => ({ left: node.getBoundingClientRect().left, right: node.getBoundingClientRect().right, scrollWidth: node.scrollWidth, clientWidth: node.clientWidth }));
      check(ctx.name, 'wide grid scrolls inside its own container on phones', gridBounds.left >= 0 && gridBounds.right <= viewport.width && (viewport.width > 600 || gridBounds.scrollWidth > gridBounds.clientWidth), gridBounds);
      await layout(ctx); await screenshot(ctx, ctx.name + '-query');
      await ctx.page.getByTestId('plan-tab-manual').click();
      await ctx.page.getByTestId('queue-cell-0-0').waitFor();
      await ctx.page.getByTestId('queue-cell-0-0').click();
      await ctx.page.getByText('已自动保存 · v1', { exact: true }).waitFor();
      await ctx.page.locator('.manual-preview-disclosure > summary').click();
      check(ctx.name, 'manual candidate details remain accessible beside the grid', await ctx.page.locator('.manual-preview-content').isVisible());
      const courtTitle = await ctx.page.locator('.queue-entry strong').first().evaluate(node => ({ height: node.getBoundingClientRect().height, lineHeight: parseFloat(getComputedStyle(node).lineHeight) }));
      check(ctx.name, 'a court name stays on one line in the narrow preview', courtTitle.height <= courtTitle.lineHeight + 1, courtTitle);
      await layout(ctx); await screenshot(ctx, ctx.name + '-manual');
    }, { credentials: readyCredentials }, viewport);
  }
}
