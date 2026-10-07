import { flushPromises, mount } from '@vue/test-utils';
import { describe, expect, it, vi } from 'vitest';

async function loadView() {
  const module = await import('./InviteRegisterView.vue').catch(() => null);
  expect(module).not.toBeNull();
  expect(module.default).toBeTruthy();
  return module.default;
}

describe('invitation registration view', () => {
  it('never reads an invite from the URL or browser storage', async () => {
    const InviteRegisterView = await loadView();
    window.history.replaceState({}, '', '/register?invite=URL_SECRET#FRAGMENT_SECRET');
    const getItem = vi.spyOn(Storage.prototype, 'getItem');
    const wrapper = mount(InviteRegisterView, {
      global: {
        provide: { httpClient: { request: vi.fn() } },
        stubs: { RouterLink: true },
      },
    });

    expect(wrapper.get('[data-testid="invite-code"]').element.value).toBe('');
    expect(getItem).not.toHaveBeenCalled();

    wrapper.unmount();
    getItem.mockRestore();
    window.history.replaceState({}, '', '/');
  });

  it('sends a manually entered code only in one POST body, then clears it', async () => {
    const InviteRegisterView = await loadView();
    window.history.replaceState({}, '', '/register');
    const request = vi.fn().mockResolvedValue({ user_id: 'user-1', username: 'Alice' });
    const setItem = vi.spyOn(Storage.prototype, 'setItem');
    const wrapper = mount(InviteRegisterView, {
      global: {
        provide: { httpClient: { request } },
        stubs: { RouterLink: true },
      },
    });

    await wrapper.get('[data-testid="invite-code"]').setValue('MANUAL_TEST_INVITE');
    await wrapper.get('[data-testid="username"]').setValue('Alice');
    await wrapper.get('[data-testid="password"]').setValue('alice synthetic password');
    await wrapper.get('form').trigger('submit');
    await flushPromises();

    expect(request).toHaveBeenCalledOnce();
    expect(request).toHaveBeenCalledWith('/api/auth/register', {
      method: 'POST',
      body: {
        invitation_code: 'MANUAL_TEST_INVITE',
        username: 'Alice',
        password: 'alice synthetic password',
      },
    });
    expect(wrapper.get('[data-testid="invite-code"]').element.value).toBe('');
    expect(window.location.href).not.toContain('MANUAL_TEST_INVITE');
    expect(setItem).not.toHaveBeenCalled();

    wrapper.unmount();
    setItem.mockRestore();
  });
});
