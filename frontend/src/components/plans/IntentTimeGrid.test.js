import { enableAutoUnmount, mount } from '@vue/test-utils';
import { afterEach, describe, expect, it } from 'vitest';
import IntentTimeGrid from './IntentTimeGrid.vue';
enableAutoUnmount(afterEach);
const setup=()=>mount(IntentTimeGrid,{props:{targetDate:'2026-11-01',courtNames:['查询中已占用场','查询中活动场','未查询的人工场'],timezoneName:'Asia/Shanghai',contextKey:'v1'}});
describe('independent reservation preferences',()=>{
 it('allows every supplied semantic court without inventory, token or freshness checks',async()=>{
  const w=setup();expect(w.findAll('td button').every(b=>!b.element.disabled)).toBe(true);
  await w.get('[data-testid="intent-cell-4-1"]').trigger('click');await w.get('[data-testid="intent-cell-5-1"]').trigger('click');await w.get('[data-testid="intent-cell-4-2"]').trigger('click');
  await w.get('[aria-label="将意向场地 2 提前"]').trigger('click');await w.get('[data-testid="apply-intent-selection"]').trigger('click');
  expect(w.emitted('apply')[0][0]).toEqual({target_date:'2026-11-01',start_time:'18:00',end_time:'19:00',duration_minutes:60,court_preferences:['未查询的人工场','查询中活动场'],intent_timezone_name:'Asia/Shanghai'});
 });
 it('rejects gaps, cancels a selected cell and clears confirmation when business context changes',async()=>{
  const w=setup();await w.get('[data-testid="intent-cell-0-0"]').trigger('click');await w.get('[data-testid="intent-cell-2-0"]').trigger('click');
  expect(w.text()).toContain('不能跨越空档');expect(w.get('[data-testid="apply-intent-selection"]').element.disabled).toBe(true);
  await w.get('[data-testid="intent-cell-2-0"]').trigger('click');expect(w.get('[data-testid="intent-cell-2-0"]').attributes('aria-pressed')).toBe('false');
  await w.setProps({contextKey:'v2'});expect(w.find('.intent-selection').exists()).toBe(false);
  await w.setProps({selectionDisabled:true});expect(w.findAll('td button').every(b=>b.element.disabled)).toBe(true);
 });
 it('keeps the plan duration limits and forbids over-four-hour choices',async()=>{
  const w=setup();for(let r=0;r<9;r++)await w.get(`[data-testid="intent-cell-${r}-0"]`).trigger('click');
  expect(w.get('[data-testid="apply-intent-selection"]').element.disabled).toBe(true);expect(w.text()).toContain('30～240分钟');
 });
});
