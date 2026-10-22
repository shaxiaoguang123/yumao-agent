import { flushPromises, mount, enableAutoUnmount } from '@vue/test-utils';
import { reactive } from 'vue';
import { afterEach, describe, expect, it, vi } from 'vitest';
import OrderQueryPanel from './OrderQueryPanel.vue';

enableAutoUnmount(afterEach);
const item = (extra = {}) => ({ reference: 'order-a', venue_name: '羽毛球1号场', booking_time: '2026-10-24 09:00-10:00',
  status: '5', status_label: '待支付', amount_display: '40.00', reservation_confirmed: false, ...extra });
const response = (extra = {}) => ({ orders: [item()], page: 1, page_size: 10, total: 11, total_pages: 2, has_next: true,
  queried_at_utc_ms: Date.UTC(2026, 9, 22, 4, 36), status_options: [{ code: '5', label: '待支付' }, { code: '4', label: '完成' }], ...extra });
const deferred = () => { let resolve; const promise = new Promise(done => { resolve = done; }); return { resolve, promise }; };
function setup(overrides = {}, props = {}) {
  const api = { query: vi.fn(async () => response()), details: vi.fn(async () => ({ order: item({ order_number: 'visible-order', created_at: '2026-10-22 12:36:00', paid_at: null }) })), ...overrides };
  const session = reactive({ status: 'authenticated', user: { user_id: 'a' }, invalidationEpoch: 0 });
  const wrapper = mount(OrderQueryPanel, { props: { api, session, credentialId: 'credential-a', ...props }, global: { stubs: { RouterLink: true } } });
  return { api, session, wrapper };
}

describe('order query', () => {
  it('shows real order states, amount, lazy details, and the pending-payment notice', async () => {
    const { wrapper, api } = setup(); await flushPromises();
    expect(api.query).toHaveBeenCalledWith({ credentialId: 'credential-a', page: 1, status: '' });
    expect(wrapper.text()).toContain('羽毛球1号场'); expect(wrapper.text()).toContain('¥40.00');
    expect(wrapper.text()).toContain('待支付'); expect(wrapper.text()).not.toContain('支付成功');
    expect(api.details).not.toHaveBeenCalled();
    await wrapper.get('button[aria-expanded]').trigger('click'); await flushPromises();
    expect(api.details).toHaveBeenCalledWith({ credentialId: 'credential-a', reference: 'order-a' });
    expect(wrapper.get('[aria-label="订单详情"]').text()).toContain('约 5 分钟');
    expect(wrapper.get('[aria-label="订单详情"]').text()).toContain('visible-order');
    expect(wrapper.findAll('button').some(button => /^(付款|支付|取消订单)$/.test(button.text()))).toBe(false);
  });

  it('requests server pagination and resets to page one for a status filter', async () => {
    const apiQuery = vi.fn(async request => response({ page: request.page, has_next: request.page === 1 }));
    const { wrapper } = setup({ query: apiQuery }); await flushPromises();
    await wrapper.findAll('button').find(button => button.text() === '下一页').trigger('click'); await flushPromises();
    expect(apiQuery).toHaveBeenLastCalledWith({ credentialId: 'credential-a', page: 2, status: '' });
    await wrapper.get('select').setValue('4'); await flushPromises();
    expect(apiQuery).toHaveBeenLastCalledWith({ credentialId: 'credential-a', page: 1, status: '4' });
  });

  it('distinguishes an empty response from a failed refresh and preserves the last good list', async () => {
    const { wrapper, api } = setup(); await flushPromises();
    api.query.mockRejectedValueOnce(Object.assign(new Error(), { code: 'order_query_rate_limited', retryAfterSeconds: 2 }));
    await wrapper.findAll('button').find(button => button.text() === '刷新订单').trigger('click'); await flushPromises();
    expect(wrapper.get('[role="alert"]').text()).toContain('2 秒');
    expect(wrapper.findAll('[data-testid="order-card"]')).toHaveLength(1);
    expect(wrapper.text()).not.toContain('暂无订单');
    api.query.mockResolvedValueOnce(response({ orders: [], total: 0, total_pages: 0, has_next: false }));
    await wrapper.findAll('button').find(button => button.text() === '刷新订单').trigger('click'); await flushPromises();
    expect(wrapper.text()).toContain('暂无订单'); expect(wrapper.find('[role="alert"]').exists()).toBe(false);
  });

  it('clears old Token results immediately and ignores their late replies', async () => {
    const a = deferred(), b = deferred();
    const { wrapper } = setup({ query: vi.fn(({ credentialId }) => credentialId === 'credential-a' ? a.promise : b.promise) });
    await wrapper.setProps({ credentialId: 'credential-b' });
    a.resolve(response()); await flushPromises();
    expect(wrapper.find('[data-testid="order-card"]').exists()).toBe(false);
    b.resolve(response({ orders: [item({ venue_name: 'B 的场地', reference: 'order-b' })] })); await flushPromises();
    expect(wrapper.text()).toContain('B 的场地'); expect(wrapper.text()).not.toContain('羽毛球1号场');
  });

  it('removes details and ignores a late response on session invalidation', async () => {
    const pending = deferred(); const { wrapper, session } = setup({ details: vi.fn(() => pending.promise) });
    await flushPromises(); await wrapper.get('button[aria-expanded]').trigger('click');
    session.status = 'unauthenticated'; session.invalidationEpoch++; await flushPromises();
    pending.resolve({ order: item({ order_number: 'must-not-appear' }) }); await flushPromises();
    expect(wrapper.find('[data-testid="order-detail"]').exists()).toBe(false);
    expect(wrapper.text()).not.toContain('must-not-appear');
    expect(wrapper.find('[data-testid="order-card"]').exists()).toBe(false);
  });

  it('does not send any request before a Token is selected', async () => {
    const { wrapper, api } = setup({}, { credentialId: '' }); await flushPromises();
    expect(api.query).not.toHaveBeenCalled(); expect(wrapper.text()).toContain('请选择已验证的 Token');
  });

  it('retries a throttled detail read without restarting the list or losing the session', async () => {
    const { wrapper, api, session } = setup(); await flushPromises();
    api.details.mockRejectedValueOnce(Object.assign(new Error(), { code: 'order_query_rate_limited', retryAfterSeconds: 1 }));
    await wrapper.get('button[aria-expanded]').trigger('click'); await flushPromises();
    const detail = wrapper.get('[data-testid="order-detail"]');
    expect(detail.get('[role="alert"]').text()).toContain('1 秒');
    await detail.findAll('button').find(button => button.text() === '重新读取详情').trigger('click'); await flushPromises();
    expect(detail.text()).toContain('visible-order');
    expect(api.query).toHaveBeenCalledOnce(); expect(api.details).toHaveBeenCalledTimes(2);
    expect(session.status).toBe('authenticated');
  });
});
