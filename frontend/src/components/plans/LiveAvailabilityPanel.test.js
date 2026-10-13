import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils';
import { reactive } from 'vue';
import { afterEach, describe, expect, it, vi } from 'vitest';
import LiveAvailabilityPanel from './LiveAvailabilityPanel.vue';

enableAutoUnmount(afterEach);
afterEach(() => vi.useRealTimers());
const credential = (id) => ({ credential_id: id, label: `测试凭据 ${id}`, enabled: true,
  account_binding_state: 'confirmed', requires_revalidation: false,
  last_confirmed_validation_state: 'confirmed_valid', expiry_state: 'valid' });
const categories = { data_state: 'live_observed_unverified', source: 'official_read_only',
  options: [{ reference: 'opaque-reference', label: '羽毛球', physical_venue_verified: false }] };
function grid() {
  return { grid_version: 'official-bookingByTime-live-observation-v1', data_state: 'live_observed_unverified',
    simulation: false, target_date: '2026-10-15', timezone_name: 'Asia/Shanghai',
    query_scope: { display_name: '羽毛球', physical_venue_verified: false },
    can_select: false, can_match: false, can_bind: false, can_book: false, can_pay: false, can_create_job: false,
    source: { data_state: 'live_observed_unverified', trust_state: 'display_only_unverified',
      price_state: 'omitted_unit_unverified', captured_at_utc_ms: Date.now(), ui_stale_after_utc_ms: Date.now() + 60000 },
    courts: [{ display_name: '测试一号场' }], rows: [{ time_label: '18:00', time_status_code: '0',
      cells: [{ state: 'observed_unknown', selectable: false }] }], notice: '所有格子只读，未核验可预约语义' };
}
async function setup(overrides = {}, credentialOverrides = {}) {
  const api = { options: vi.fn(async () => ({ enabled: true })), categories: vi.fn(async () => categories),
    grid: vi.fn(async () => grid()), ...overrides };
  const credentialApi = { list: vi.fn(async () => ({ credentials: [credential('a'), credential('b')] })), ...credentialOverrides };
  const session = reactive({ status: 'authenticated', user: { user_id: 'user-a' }, csrfToken: 'csrf-a' });
  const wrapper = mount(LiveAvailabilityPanel, { props: { api, credentialApi, session, targetDate: '2026-10-15', contextKey: 'plan-v1' } });
  await flushPromises();
  return { api, credentialApi, session, wrapper };
}
async function load(wrapper) { await wrapper.get('[data-testid="load-live-categories"]').trigger('click'); await flushPromises(); }
async function query(wrapper) { await wrapper.get('[data-testid="query-live-grid"]').trigger('click'); await flushPromises(); }

describe('official read-only observation flow', () => {
  it('uses explicit clicks, owned credentials and opaque category refs, and displays no selection controls', async () => {
    const { wrapper, api } = await setup();
    expect(api.categories).not.toHaveBeenCalled();
    await load(wrapper); await query(wrapper);
    expect(api.categories).toHaveBeenCalledWith('a');
    expect(api.grid).toHaveBeenCalledWith({ credentialId: 'a', scopeReference: 'opaque-reference', targetDate: '2026-10-15' });
    const table = wrapper.get('[data-testid="live-availability-grid"]');
    expect(table.text()).toContain('状态未知');
    expect(table.text()).toContain('价格单位尚未核验');
    expect(table.findAll('button,input').length).toBe(0);
  });
  it('clears observations on plan/date change and ignores late responses', async () => {
    let finish;
    const { wrapper } = await setup({ grid: vi.fn(() => new Promise((resolve) => { finish = resolve; })) });
    await load(wrapper); await wrapper.get('[data-testid="query-live-grid"]').trigger('click');
    await wrapper.setProps({ targetDate: '2026-10-16', contextKey: 'plan-v2' });
    finish(grid()); await flushPromises();
    expect(wrapper.find('[data-testid="live-availability-grid"]').exists()).toBe(false);
    expect(wrapper.get('[data-testid="query-live-grid"]').element.disabled).toBe(false);
  });
  it('invalidates category references when the selected credential changes', async () => {
    const { wrapper } = await setup();
    await load(wrapper); await query(wrapper);
    await wrapper.get('[data-testid="live-credential"]').setValue('b');
    await flushPromises();
    expect(wrapper.find('[data-testid="live-category"]').exists()).toBe(false);
    expect(wrapper.find('[data-testid="live-availability-grid"]').exists()).toBe(false);
  });
  it('drops a pending response after Session invalidation', async () => {
    let finish;
    const { wrapper, session } = await setup({ grid: vi.fn(() => new Promise((resolve) => { finish = resolve; })) });
    await load(wrapper); await wrapper.get('[data-testid="query-live-grid"]').trigger('click');
    session.status = 'unauthenticated'; session.user = null;
    await flushPromises(); finish(grid()); await flushPromises();
    expect(wrapper.find('[data-testid="live-availability-grid"]').exists()).toBe(false);
    expect(wrapper.find('[data-testid="live-category"]').exists()).toBe(false);
  });
  it('reports the service window error and never falls back to old data', async () => {
    const { wrapper, api } = await setup(); await load(wrapper); await query(wrapper);
    api.grid.mockRejectedValueOnce({ code: 'booking_window_closed' }); await query(wrapper);
    expect(wrapper.text()).toContain('不在服务端允许的查询窗口');
    expect(wrapper.find('[data-testid="live-availability-grid"]').exists()).toBe(false);
  });
  it('marks the observation expired and rejects execution-capable payloads', async () => {
    vi.useFakeTimers();
    const { wrapper, api } = await setup(); await load(wrapper); await query(wrapper);
    await vi.advanceTimersByTimeAsync(60001);
    expect(wrapper.get('[data-testid="live-grid-expired"]').text()).toContain('观察已过期');
    api.grid.mockResolvedValueOnce({ ...grid(), can_book: true }); await query(wrapper);
    expect(wrapper.text()).toContain('来源标记无效');
    expect(wrapper.find('[data-testid="live-availability-grid"]').exists()).toBe(false);
  });
  it('hides query controls when production/local configuration disables reads', async () => {
    const { wrapper, credentialApi } = await setup({ options: vi.fn(async () => ({ enabled: false })) });
    expect(wrapper.find('[data-testid="load-live-categories"]').exists()).toBe(false);
    expect(credentialApi.list).not.toHaveBeenCalled();
  });
});
