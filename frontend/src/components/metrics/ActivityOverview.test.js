import { flushPromises, mount, enableAutoUnmount } from '@vue/test-utils';
import { reactive } from 'vue';
import { createMemoryHistory, createRouter } from 'vue-router';
import { afterEach, describe, expect, it, vi } from 'vitest';
import ActivityOverview from './ActivityOverview.vue';
import { metricsFixture } from '../../../test-support/diagnostics.js';
enableAutoUnmount(afterEach);

async function setup({ system = false, role = 'user', response, pending } = {}) {
  const session = reactive({ status: 'authenticated', user: { role } });
  const api = { overview: vi.fn().mockImplementation(() => pending || Promise.resolve(response || metricsFixture())), system: vi.fn().mockResolvedValue(response || metricsFixture('system')) };
  const router = createRouter({ history: createMemoryHistory(), routes: [{ path: '/', component: { template: '<div />' } }, { path: '/admin/logs', name: 'admin-logs', component: { template: '<div />' } }] });
  await router.push('/');
  const wrapper = mount(ActivityOverview, { props: { system }, global: { plugins: [router], provide: { sessionStore: session, diagnosticsApi: api } } });
  await flushPromises();
  return { wrapper, api, session };
}

describe('activity metrics', () => {
  it('shows personal facts, independent duration counts and accessible chart labels', async () => {
    const { wrapper, api } = await setup();
    expect(api.overview).toHaveBeenCalledOnce();
    expect(api.system).not.toHaveBeenCalled();
    expect(wrapper.text()).toContain('2 小时 4 · 1 小时 2');
    expect(wrapper.text()).toContain('候选数量不代表已预约场次');
    expect(wrapper.get('ol[aria-label="近七天执行任务状态"]').findAll('li')).toHaveLength(7);
    expect(wrapper.findAll('li[tabindex="0"]').at(-1).attributes('aria-label')).toContain('成功 1');
  });

  it('does not show zero values as facts while loading', async () => {
    const { wrapper } = await setup({ pending: new Promise(() => {}) });
    expect(wrapper.text()).toContain('正在读取运行指标');
    expect(wrapper.find('.activity-cards').exists()).toBe(false);
  });

  it('refreshes personal facts when the authenticated user changes without a role change', async () => {
    const { wrapper, session, api } = await setup();
    const next = metricsFixture(); next.queues.upcoming = 7;
    api.overview.mockResolvedValue(next);
    session.user.user_id = 'another-user'; await flushPromises();
    expect(api.overview).toHaveBeenCalledTimes(2);
    expect(wrapper.get('.activity-card strong').text()).toBe('7');
  });

  it('gates the system endpoint by the live administrator role', async () => {
    const { wrapper, api, session } = await setup({ system: true });
    expect(api.system).not.toHaveBeenCalled();
    expect(wrapper.find('section').exists()).toBe(false);
    session.user.role = 'admin'; await flushPromises();
    expect(api.system).toHaveBeenCalledOnce();
    expect(wrapper.text()).toContain('全站运行概览');
    expect(wrapper.text()).toContain('123 ms');
  });

  it('keeps business metrics visible when diagnostic collection is unavailable', async () => {
    const data = metricsFixture('system'); data.diagnostics = { available: false };
    const { wrapper } = await setup({ system: true, role: 'admin', response: data });
    expect(wrapper.text()).toContain('未来队列');
    expect(wrapper.text()).toContain('日志尚未就绪或采集未启用');
  });

  it('retries failed requests and discards late responses after permission changes', async () => {
    let resolve;
    const pending = new Promise(done => { resolve = done; });
    const { wrapper, session, api } = await setup({ pending });
    session.status = 'unauthenticated'; await flushPromises();
    resolve(metricsFixture()); await flushPromises();
    expect(wrapper.find('.activity-cards').exists()).toBe(false);
    api.overview.mockRejectedValueOnce(new Error('synthetic'));
    session.status = 'authenticated'; await flushPromises();
    expect(wrapper.get('[role="alert"]').text()).toContain('指标暂时不可用');
    api.overview.mockResolvedValue(metricsFixture());
    await wrapper.get('button').trigger('click'); await flushPromises();
    expect(wrapper.find('.activity-cards').exists()).toBe(true);
  });
});
