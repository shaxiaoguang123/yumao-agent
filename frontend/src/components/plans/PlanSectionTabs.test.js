import { flushPromises, mount } from '@vue/test-utils';
import { describe, expect, it, vi } from 'vitest';
import PlanSectionTabs from './PlanSectionTabs.vue';

describe('plan section tabs', () => {
  it('keeps the selected tab visible after resize and removes its listener', async () => {
    const addListener = vi.spyOn(window, 'addEventListener');
    const removeListener = vi.spyOn(window, 'removeEventListener');
    const wrapper = mount(PlanSectionTabs, { props: { modelValue: 'agent' } });
    await flushPromises();
    const resizeHandler = addListener.mock.calls.filter(([type]) => type === 'resize').at(-1)?.[1];
    const nav = wrapper.get('[role="tablist"]').element;
    let navWidth = 200;
    let activeContentLeft = 700;
    Object.defineProperty(nav, 'clientWidth', { configurable: true, get: () => navWidth });
    Object.defineProperty(nav, 'scrollWidth', { configurable: true, value: 900 });
    Object.defineProperty(nav, 'getBoundingClientRect', { configurable: true, value: () => ({ left: 16 }) });
    for (const tab of nav.querySelectorAll('[role="tab"]')) {
      Object.defineProperty(tab, 'offsetWidth', { configurable: true, value: 80 });
      Object.defineProperty(tab, 'getBoundingClientRect', {
        configurable: true,
        value: () => ({ left: 16 + activeContentLeft - nav.scrollLeft }),
      });
    }
    nav.scrollLeft = 120;

    window.dispatchEvent(new Event('resize'));
    await flushPromises();
    expect(nav.scrollLeft).toBe(640);

    navWidth = 160;
    window.dispatchEvent(new Event('resize'));
    await flushPromises();
    expect(nav.scrollLeft).toBe(660);

    activeContentLeft = 1060;
    await wrapper.setProps({ modelValue: 'orders' });
    await flushPromises();
    expect(nav.scrollLeft).toBe(1020);

    wrapper.unmount();
    expect(removeListener).toHaveBeenCalledWith('resize', resizeHandler);
    addListener.mockRestore();
    removeListener.mockRestore();
  });
});
