import { credential, viewports } from './fixtures.mjs';

export const orderStatusOptions = ['待使用', '取消预约', '违约', '完成', '待支付', '待评价', '取消预约审批中', '使用中', '失效', '包场待审批', '包场审批不通过', '挂账待审批', '挂账审批不通过', '等待管理员审批', '预约审批未通过'].map((label, index) => ({ code: String(index + 1), label }));

export function syntheticOrders(credentialId) {
  return ['5', '1', '4', '6', '8', '2', '3', '7', '9', '10', '11', '12', '13', '14', '15'].map((status, index) => ({
    reference: `synthetic-${credentialId}-${index}`,
    venue_name: `${credentialId === 'visual-other' ? 'B · ' : ''}羽毛球${index % 10 + 1}号场`,
    appointment_date: '2026-10-24', booking_time: '2026-10-24 09:00-10:00',
    order_number: `synthetic-order-${index}`, status, status_label: orderStatusOptions.find(item => item.code === status).label,
    reservation_confirmed: ['1', '4', '6', '8'].includes(status), amount_display: '40.00',
    created_at: '2026-10-22 12:36:00', paid_at: null, use_expires_at: '2026-10-24 10:00',
  }));
}

export async function runOrders(qa) {
  const { BASE, scenario, check, layout, screenshot, count } = qa;
  const credentials = [credential('visual-confirmed', 'Token A', { has_payment_password: false }), credential('visual-other', 'Token B', { has_payment_password: false })];
  for (const viewport of viewports) await scenario(`orders-${viewport.name}`, 'user', async ctx => {
    await ctx.page.goto(BASE + '/plans?tab=orders');
    const panel = ctx.page.getByTestId('order-query-panel');
    await panel.getByTestId('order-card').first().waitFor();
    check(ctx.name, 'order deep link needs a valid Token but no payment password', new URL(ctx.page.url()).pathname === '/plans' && await ctx.page.getByTestId('plan-tab-orders').getAttribute('aria-selected') === 'true');
    check(ctx.name, 'the active order tab is visible even in a horizontally scrolling mobile tab bar', await ctx.page.getByTestId('plan-tab-orders').evaluate(button => { const box = button.getBoundingClientRect(); return box.left >= 0 && box.right <= document.documentElement.clientWidth + 1; }));
    check(ctx.name, 'first page contains 10 orders and all 15 official filter states', await panel.getByTestId('order-card').count() === 10 && await panel.getByLabel('订单状态').locator('option').count() === 16);
    await panel.getByTestId('order-card').first().getByRole('button', { name: /订单详情/ }).click();
    const detail = panel.getByTestId('order-detail'); await detail.getByText('订单尚未支付。', { exact: false }).waitFor();
    check(ctx.name, 'pending detail stays unpaid and offers no payment or cancellation action', (await detail.innerText()).includes('约 5 分钟') && await panel.getByRole('button', { name: /^(付款|支付|取消订单)$/ }).count() === 0);
    await layout(ctx); await screenshot(ctx, `${ctx.name}-detail`);
    await panel.getByLabel('订单状态').selectOption('4');
    await panel.getByText('共 1 条', { exact: false }).waitFor();
    check(ctx.name, 'status filtering changes the list and resets pagination', await panel.getByTestId('order-card').count() === 1 && await panel.getByRole('button', { name: '上一页', exact: true }).isDisabled());
    await panel.getByLabel('订单状态').selectOption('');
    await panel.getByText('共 15 条', { exact: false }).waitFor();
    await panel.getByRole('button', { name: '下一页', exact: true }).click();
    await panel.getByText('第 2 / 2 页', { exact: false }).waitFor();
    check(ctx.name, 'server pagination reaches the final five orders', await panel.getByTestId('order-card').count() === 5 && await panel.getByRole('button', { name: '下一页', exact: true }).isDisabled());
    await panel.locator('.credential-popover > summary').click();
    await panel.getByTestId('selection-credential').selectOption('visual-other');
    await panel.getByTestId('order-card').first().getByText('B · 羽毛球1号场', { exact: true }).waitFor();
    await panel.locator('.credential-popover > summary').click();
    check(ctx.name, 'switching Token fetches that account and resets to page one', (await panel.innerText()).includes('第 1 / 2 页') && await panel.getByTestId('order-detail').count() === 0);
    ctx.state.orderQueryError = true;
    await panel.getByRole('button', { name: '刷新订单', exact: true }).click();
    await panel.getByRole('alert').waitFor();
    check(ctx.name, 'rate limits preserve session and previously read orders', (await panel.getByRole('alert').innerText()).includes('2 秒') && await panel.getByTestId('order-card').count() === 10 && new URL(ctx.page.url()).pathname === '/plans');
    await layout(ctx); await screenshot(ctx, `${ctx.name}-rate-limit`);
    ctx.state.orderQueryError = false; ctx.state.orderQueryEmpty = true;
    await panel.getByRole('button', { name: '刷新订单', exact: true }).click();
    await panel.getByText('当前 Token 在此状态下暂无订单。', { exact: true }).waitFor();
    check(ctx.name, 'empty orders are explicit and remain distinct from errors', await panel.getByRole('alert').count() === 0 && await panel.getByTestId('order-card').count() === 0);
    check(ctx.name, 'only read-only order APIs were called', count(ctx, '/api/orders/query') >= 5 && count(ctx, '/api/orders/details') === 1 && ctx.state.requests.every(request => !/createBooking|openPlatFormPayOrder|cancelOrder|refund/.test(request.path)));
    await layout(ctx); await screenshot(ctx, `${ctx.name}-empty`);
  }, { credentials }, viewport);
}
