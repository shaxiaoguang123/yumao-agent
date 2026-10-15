import { enableAutoUnmount, mount } from '@vue/test-utils';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import TokenExpiryBadge from './TokenExpiryBadge.vue';
enableAutoUnmount(afterEach);
beforeEach(()=>{vi.useFakeTimers();vi.setSystemTime(new Date('2026-10-14T10:00:00Z'));});afterEach(()=>vi.useRealTimers());
describe('safe credential expiry metadata',()=>{
 it('highlights and pulses within seven days, then changes to expired',async()=>{
  const w=mount(TokenExpiryBadge,{props:{credential:{token_expires_at_utc:'2026-10-14T10:01:00Z'}}});
  expect(w.classes()).toContain('is-urgent');expect(w.classes()).toContain('is-pulsing');expect(w.text()).toContain('剩1天');
  await vi.advanceTimersByTimeAsync(60000);expect(w.text()).toContain('已过期');expect(w.classes()).not.toContain('is-pulsing');
 });
 it('does not manufacture an expiry for missing metadata and leaves long-lived tokens neutral',()=>{
  const missing=mount(TokenExpiryBadge,{props:{credential:{expiry_state:'expiry_ok'}}});expect(missing.text()).toContain('到期未知');expect(missing.classes()).not.toContain('is-urgent');
  const valid=mount(TokenExpiryBadge,{props:{credential:{token_expires_at_utc:'2026-11-14T10:00:00Z'}}});expect(valid.classes()).not.toContain('is-urgent');expect(valid.text()).toContain('剩31天');
 });
});
