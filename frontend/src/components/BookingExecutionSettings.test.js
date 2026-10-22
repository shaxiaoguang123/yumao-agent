import { flushPromises, mount } from '@vue/test-utils';
import { describe, expect, it, vi } from 'vitest';
import BookingExecutionSettings from './BookingExecutionSettings.vue';

const base = {
  reconciliation_time: '00:30', clock_calibration_lead_ms: 1000, start_offset_ms: 0,
  booking_node_delay_ms: 0, booking_by_time_delay_ms: 0, get_user_info_delay_ms: 0,
  get_pay_price_delay_ms: 0, create_booking_delay_ms: 0,
  open_platform_pay_order_delay_ms: 0, payment_verify_delay_ms: 0,
  payment_verify_interval_ms: 3000, candidate_interval_ms: 0,
};

function result(version = 0, settings = base) {
  return { version, settings: { ...settings }, worker_enabled: true };
}

describe('BookingExecutionSettings', () => {
  it('loads and saves one shared schedule profile with version fencing', async () => {
    const api = {
      executionSettings: vi.fn(async () => result()),
      updateExecutionSettings: vi.fn(async (version, settings) => result(version + 1, settings)),
    };
    const wrapper = mount(BookingExecutionSettings, { props: { api } });
    await flushPromises();
    expect(api.executionSettings).toHaveBeenCalledOnce();
    expect(wrapper.text()).toContain('执行器已启用');
    await wrapper.get('input[type="time"]').setValue('01:15');
    await wrapper.get('input[type="number"]').setValue('850');
    await wrapper.get('form').trigger('submit');
    await flushPromises();
    expect(api.updateExecutionSettings).toHaveBeenCalledWith(
      0, { ...base, reconciliation_time: '01:15', clock_calibration_lead_ms: 850 },
    );
    expect(wrapper.text()).toContain('名下所有 Token 会在下次复核时使用这组设置');
  });

  it('discloses when the scheduled worker has not been enabled', async () => {
    const api = {
      executionSettings: vi.fn(async () => ({ ...result(), worker_enabled: false })),
      updateExecutionSettings: vi.fn(),
    };
    const wrapper = mount(BookingExecutionSettings, { props: { api } });
    await flushPromises();
    expect(wrapper.text()).toContain('执行器未启用');
  });

  it('explains every configurable delay and exposes all timing inputs', async () => {
    const api = {
      executionSettings: vi.fn(async () => result()),
      updateExecutionSettings: vi.fn(),
    };
    const wrapper = mount(BookingExecutionSettings, { props: { api } });
    await flushPromises();
    expect(wrapper.get('[aria-label="查看执行时间和延迟说明"]').attributes('aria-describedby')).toBe('execution-help-content');
    expect(wrapper.get('#execution-help-content').text()).toContain('预约人数固定填写 5');
    expect(wrapper.get('#execution-help-content').text()).toContain('两次查询之间的等待');
    expect(wrapper.findAll('input[type="number"]')).toHaveLength(11);
    expect(wrapper.get('input[name="open_platform_pay_order_delay_ms"]').attributes('max')).toBe('120000');
    expect(wrapper.find('input[name="payment_verify_interval_ms"]').exists()).toBe(true);
    expect(wrapper.find('input[name="candidate_interval_ms"]').exists()).toBe(true);
  });
});
