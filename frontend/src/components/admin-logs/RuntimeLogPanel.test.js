import { flushPromises, mount, enableAutoUnmount } from '@vue/test-utils';
import { reactive } from 'vue';
import { afterEach, describe, expect, it, vi } from 'vitest';
import RuntimeLogPanel from './RuntimeLogPanel.vue';
import { logsFixture, logFixture } from '../../../test-support/diagnostics.js';
enableAutoUnmount(afterEach);

async function setup(role = 'admin', override = {}) {
  const session = reactive({ status: 'authenticated', user: { role } });
  const api = { logs: vi.fn().mockResolvedValue(logsFixture()), detail: vi.fn().mockResolvedValue({ event: logFixture(), related: [logFixture()] }), ...override };
  const wrapper = mount(RuntimeLogPanel, { global: { provide: { sessionStore: session, diagnosticsApi: api } } });
  await flushPromises();
  return { wrapper, api, session };
}

describe('administrator runtime logs', () => {
  it('shows a filterable list and safe detail timeline', async () => {
    const { wrapper, api } = await setup();
    expect(wrapper.text()).toContain('provider_timeout');
    expect(wrapper.text()).toContain('日志采集已就绪');
    expect(api.logs.mock.calls[0][0].hours).toBe(24);
    await wrapper.get('button[aria-label="查看第 5 条日志详情"]').trigger('click'); await flushPromises();
    expect(wrapper.text()).toContain('代码位置 · TimeoutError');
    expect(wrapper.text()).toContain('backend/ai/provider.py:190');
    expect(wrapper.text()).toContain('关联事件时间线');
    expect(wrapper.get('.runtime-event.is-selected').find('[aria-label="日志详情"]').exists()).toBe(true);
    expect(wrapper.findAll('.runtime-event').filter(row => row.find('[aria-label="日志详情"]').exists())).toHaveLength(1);
    await wrapper.findAll('button').find(item => item.text() === '关闭详情').trigger('click');
    expect(wrapper.find('[aria-label="日志详情"]').exists()).toBe(false);
  });

  it('keeps detail loading and errors inside the selected log row', async () => {
    let rejectDetail;
    const { wrapper } = await setup('admin', { detail: vi.fn(() => new Promise((_, reject) => { rejectDetail = reject; })) });
    const selectedRow = wrapper.get('.runtime-event');
    await selectedRow.get('button[aria-label="查看第 5 条日志详情"]').trigger('click');
    expect(selectedRow.get('[role="status"]').text()).toContain('正在读取日志详情');
    rejectDetail(new Error('unavailable'));
    await flushPromises();
    expect(selectedRow.get('[role="alert"]').text()).toContain('详情暂时不可用');
    expect(wrapper.findAll('.runtime-event').filter(row => row.find('[role="alert"]').exists())).toHaveLength(1);
  });

  it('shows only the latest selection when detail requests resolve out of order', async () => {
    const events = [logFixture(5), logFixture(6)];
    let resolveFirst;
    const api = {
      logs: vi.fn().mockResolvedValue({ ...logsFixture(), events }),
      detail: vi.fn(id => id === 5
        ? new Promise(resolve => { resolveFirst = resolve; })
        : Promise.resolve({ event: logFixture(id), related: [] })),
    };
    const { wrapper } = await setup('admin', api);
    await wrapper.get('button[aria-label="查看第 5 条日志详情"]').trigger('click');
    await wrapper.get('button[aria-label="查看第 6 条日志详情"]').trigger('click');
    await flushPromises();
    resolveFirst({ event: logFixture(5), related: [] });
    await flushPromises();
    expect(wrapper.get('.runtime-event.is-selected').text()).toContain('EVENT #6');
    expect(wrapper.findAll('[aria-label="日志详情"]')).toHaveLength(1);
    expect(wrapper.find('[aria-label="日志详情"]').text()).toContain('EVENT #6');
  });

  it('does not request logs for ordinary users and removes data after role revocation', async () => {
    const { wrapper, api, session } = await setup('user');
    expect(api.logs).not.toHaveBeenCalled();
    session.user.role = 'admin'; await flushPromises();
    expect(api.logs).toHaveBeenCalledOnce();
    session.user.role = 'user'; await flushPromises();
    expect(wrapper.find('[aria-label="运行日志列表"]').exists()).toBe(false);
  });

  it('applies level and module filters and cursor pagination without shifting the time window', async () => {
    const first = logsFixture(); first.next_cursor = 5;
    const { wrapper, api } = await setup('admin', { logs: vi.fn().mockResolvedValue(first) });
    const until = first.window.until;
    api.logs.mockResolvedValue({ ...logsFixture(), events: [logFixture(4)] });
    await wrapper.findAll('button').find(item => item.text() === '加载更早日志').trigger('click'); await flushPromises();
    expect(api.logs.mock.calls[1][0]).toMatchObject({ until, before: 5 });
    expect(wrapper.findAll('.runtime-event')).toHaveLength(2);
    const selects = wrapper.findAll('select');
    await selects[1].setValue('warning'); await selects[2].setValue('agent');
    await wrapper.get('form').trigger('submit'); await flushPromises();
    expect(api.logs.mock.calls.at(-1)[0]).toMatchObject({ level: 'warning', module: 'agent' });
    expect(wrapper.findAll('.runtime-event')).toHaveLength(1);
  });

  it('shows an unavailable state rather than claiming an empty healthy log', async () => {
    const { wrapper, api } = await setup('admin', { logs: vi.fn().mockRejectedValue({ status: 503, requestId: 'a'.repeat(32) }) });
    expect(wrapper.get('[role="alert"]').text()).toContain('请求编号');
    expect(wrapper.text()).not.toContain('范围内没有已采集');
    api.logs.mockResolvedValue({ ...logsFixture(), events: [] });
    await wrapper.findAll('button').find(item => item.text() === '刷新日志').trigger('click'); await flushPromises();
    expect(wrapper.text()).toContain('范围内没有已采集');
  });

  it('keeps the initial log loading state visible until the list request finishes', async () => {
    let resolveLogs;
    const session = reactive({ status: 'authenticated', user: { role: 'admin' } });
    const api = { logs: vi.fn(() => new Promise(resolve => { resolveLogs = resolve; })), detail: vi.fn() };
    const wrapper = mount(RuntimeLogPanel, { global: { provide: { sessionStore: session, diagnosticsApi: api } } });
    expect(wrapper.get('[role="status"]').text()).toContain('正在读取运行日志');
    resolveLogs(logsFixture());
    await flushPromises();
    expect(wrapper.find('[role="status"]').exists()).toBe(false);
    expect(wrapper.findAll('.runtime-event')).toHaveLength(1);
  });

  it('ignores a late detail response after filters change and escapes all text', async () => {
    let resolve;
    const { wrapper } = await setup('admin', { detail: vi.fn().mockImplementation(() => new Promise(done => { resolve = done; })) });
    await wrapper.get('button[aria-label="查看第 5 条日志详情"]').trigger('click');
    await wrapper.get('form').trigger('submit'); await flushPromises();
    resolve({ event: { ...logFixture(), code: '<img src=x onerror=alert(1)>' }, related: [] }); await flushPromises();
    expect(wrapper.find('[aria-label="日志详情"]').exists()).toBe(false);
    expect(wrapper.find('img').exists()).toBe(false);
  });
});
