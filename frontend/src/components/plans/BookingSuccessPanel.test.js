import { flushPromises, mount } from '@vue/test-utils';
import { describe, expect, it, vi } from 'vitest';
import BookingSuccessPanel from './BookingSuccessPanel.vue';

const session = { status: 'authenticated', user: { user_id: 'user-a' }, invalidationEpoch: 0 };

describe('BookingSuccessPanel', () => {
  it('shows only an order-query-confirmed booking summary', async () => {
    const api = { executionSuccesses: vi.fn(async () => ({
      worker_enabled: true,
      successes: [{
        run_id: 'run-a', credential_id: 'credential-a', credential_label: '主账号',
        target_date: '2026-10-24', scope_label: '羽毛球', court_preference: '6号场',
        start_time: '14:00', end_time: '16:00', duration_minutes: 120,
        confirmed_at_utc_ms: Date.UTC(2026, 9, 22, 0), verification: 'order_query',
      }],
    })) };
    const wrapper = mount(BookingSuccessPanel, { props: { api, session } });
    await flushPromises();
    expect(api.executionSuccesses).toHaveBeenCalledOnce();
    expect(wrapper.text()).toContain('预约成功');
    expect(wrapper.text()).toContain('2026-10-24 · 14:00–16:00 · 6号场');
    expect(wrapper.text()).toContain('查单确认');
  });

  it('fails closed when the server response is not order-query verified', async () => {
    const api = { executionSuccesses: vi.fn(async () => ({
      worker_enabled: true,
      successes: [{ credential_id: 'credential-a', target_date: '2026-10-24',
        confirmed_at_utc_ms: 1, verification: 'payment_request' }],
    })) };
    const wrapper = mount(BookingSuccessPanel, { props: { api, session } });
    await flushPromises();
    expect(wrapper.get('[role="alert"]').text()).toContain('抢票结果读取失败');
  });
});
