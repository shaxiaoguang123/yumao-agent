import { flushPromises, mount } from '@vue/test-utils';
import { describe, expect, it, vi } from 'vitest';
import BookingExecutionSettings from './BookingExecutionSettings.vue';

const base = {
  reconciliation_time: '00:30', clock_calibration_lead_ms: 1000, start_offset_ms: 0,
  booking_node_delay_ms: 0, booking_by_time_delay_ms: 0, get_user_info_delay_ms: 0,
  get_children_delay_ms: 0, get_pay_price_delay_ms: 0, create_booking_delay_ms: 0,
  open_platform_pay_order_delay_ms: 0, payment_verify_delay_ms: 0,
};

function result(credentialId, version = 0, settings = base) {
  return { credential_id: credentialId, version, settings: { ...settings }, worker_enabled: true };
}

describe('BookingExecutionSettings', () => {
  it('loads and saves schedule controls for the selected credential with version fencing', async () => {
    const api = {
      executionSettings: vi.fn(async id => result(id)),
      updateExecutionSettings: vi.fn(async (id, version, settings) => result(id, version + 1, settings)),
    };
    const wrapper = mount(BookingExecutionSettings, {
      props: { api, credentialId: 'credential-a' },
    });
    await flushPromises();
    expect(api.executionSettings).toHaveBeenCalledWith('credential-a');
    expect(wrapper.text()).toContain('执行器已启用');
    await wrapper.get('input[type="time"]').setValue('01:15');
    await wrapper.get('input[type="number"]').setValue('850');
    await wrapper.get('form').trigger('submit');
    await flushPromises();
    expect(api.updateExecutionSettings).toHaveBeenCalledWith(
      'credential-a', 0, { ...base, reconciliation_time: '01:15', clock_calibration_lead_ms: 850 },
    );
    expect(wrapper.text()).toContain('已保存；非空队列会按这些设置处理并执行。');
  });

  it('discloses when the scheduled worker has not been enabled', async () => {
    const api = {
      executionSettings: vi.fn(async id => ({ ...result(id), worker_enabled: false })),
      updateExecutionSettings: vi.fn(),
    };
    const wrapper = mount(BookingExecutionSettings, {
      props: { api, credentialId: 'credential-b' },
    });
    await flushPromises();
    expect(wrapper.text()).toContain('执行器未启用');
  });

  it('fences a settings response after switching to another credential', async () => {
    let finish;
    const api = {
      executionSettings: vi.fn(id => id === 'credential-a'
        ? new Promise(resolve => { finish = resolve; })
        : Promise.resolve(result(id))),
      updateExecutionSettings: vi.fn(),
    };
    const wrapper = mount(BookingExecutionSettings, {
      props: { api, credentialId: 'credential-a' },
    });
    await wrapper.setProps({ credentialId: 'credential-b' });
    await flushPromises();
    finish(result('credential-a', 9, { ...base, reconciliation_time: '06:00' }));
    await flushPromises();
    expect(wrapper.get('input[type="time"]').element.value).toBe('00:30');
  });

  it('keeps settings out of the editor until a plan credential is selected', async () => {
    const api = { executionSettings: vi.fn(), updateExecutionSettings: vi.fn() };
    const wrapper = mount(BookingExecutionSettings, { props: { api, credentialId: '' }, global: { stubs: { RouterLink: { template: '<a><slot /></a>' } } } });
    await flushPromises();
    expect(wrapper.text()).toContain('在计划页上方选择一个预约 Token');
    expect(api.executionSettings).not.toHaveBeenCalled();
    await wrapper.setProps({ credentialId: 'credential-a' });
    await flushPromises();
    expect(api.executionSettings).toHaveBeenCalledWith('credential-a');
  });
});
