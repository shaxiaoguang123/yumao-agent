import {enableAutoUnmount,mount} from '@vue/test-utils';
import {afterEach,describe,expect,it} from 'vitest';
import LiveAvailabilityGrid from './LiveAvailabilityGrid.vue';
enableAutoUnmount(afterEach);
const cell=(state='observed_clear_unmarked')=>({state,intent_selectable:state==='observed_clear_unmarked',selectable:false,activity_type:state==='observed_activity_occupied'?3:null});
function grid(){return {target_date:'2026-10-15',timezone_name:'Asia/Shanghai',query_scope:{display_name:'羽毛球'},can_select_intent:true,client_selection_window:'open',source:{captured_at_utc_ms:Date.now(),ui_stale_after_utc_ms:Date.now()+60000},selection_limits:{min_slots_observed:1,max_slots_observed:4},courts:[{display_name:'任意首选场'},{display_name:'任意备选场'},{display_name:'占用场'}],rows:[{time_label:'18:00',intent_start_time:'18:00',intent_end_time:'19:00',time_status_code:'0',cells:[cell(),cell(),cell('observed_reserved')]},{time_label:'19:00',intent_start_time:'19:00',intent_end_time:'20:00',time_status_code:'0',cells:[cell(),cell(),cell('observed_unknown')]}]};}
describe('official display selection for semantic intent',()=>{
 it('selects any returned clear court, cancels cells, orders alternatives and emits only semantic values',async()=>{
  const wrapper=mount(LiveAvailabilityGrid,{props:{grid:grid()}});
  await wrapper.get('[data-testid="live-cell-0-1"]').trigger('click');await wrapper.get('[data-testid="live-cell-1-1"]').trigger('click');
  await wrapper.get('[data-testid="live-cell-0-0"]').trigger('click');
  expect(wrapper.get('.observed-selection').text()).toContain('首选 · 任意备选场');
  await wrapper.get('[aria-label="将场地 2 提前"]').trigger('click');
  await wrapper.get('[data-testid="apply-live-selection"]').trigger('click');
  const payload=wrapper.emitted('apply')[0][0];
  expect(payload).toMatchObject({target_date:'2026-10-15',start_time:'18:00',end_time:'20:00',duration_minutes:120,court_preferences:['任意首选场','任意备选场']});
  expect(Object.keys(payload).sort()).toEqual(['court_preferences','duration_minutes','end_time','observation_expires_at_utc_ms','observation_timezone_name','start_time','target_date'].sort());
  await wrapper.get('[aria-label="移除场地 2"]').trigger('click');expect(wrapper.get('.observed-selection').text()).not.toContain('备选 1');
  await wrapper.get('[data-testid="live-cell-0-0"]').trigger('click');expect(wrapper.get('[data-testid="live-cell-0-0"]').attributes('aria-pressed')).toBe('false');
 });
 it('disables occupied, activity, unbookable and unknown states',()=>{
  const data=grid();data.courts=[{display_name:'占用'},{display_name:'活动'},{display_name:'禁用'},{display_name:'未知'}];
  data.rows=data.rows.slice(0,1);data.rows[0].cells=['observed_reserved','observed_activity_occupied','observed_unbookable','observed_unknown'].map(cell);
  const wrapper=mount(LiveAvailabilityGrid,{props:{grid:data}});
  expect(wrapper.findAll('.observation-cell').every(button=>button.element.disabled)).toBe(true);
  expect(wrapper.find('.official-course-3').exists()).toBe(true);
 });
 it('rejects real time gaps and clears pending selection when context or expiration changes',async()=>{
  const data=grid();data.rows[0].intent_end_time='18:30';
  const wrapper=mount(LiveAvailabilityGrid,{props:{grid:data,contextKey:'v1'}});
  await wrapper.get('[data-testid="live-cell-0-0"]').trigger('click');await wrapper.get('[data-testid="live-cell-1-0"]').trigger('click');
  expect(wrapper.text()).toContain('不能跨越空档');expect(wrapper.get('[data-testid="apply-live-selection"]').element.disabled).toBe(true);
  await wrapper.setProps({contextKey:'v2'});expect(wrapper.find('.observed-selection').exists()).toBe(false);
  await wrapper.get('[data-testid="live-cell-0-0"]').trigger('click');await wrapper.setProps({expired:true});
  expect(wrapper.find('.observed-selection').exists()).toBe(false);expect(wrapper.get('[data-testid="live-cell-0-0"]').element.disabled).toBe(true);
 });
 it('does not select if the official client time window is unknown or closed',()=>{
  const data=grid();data.client_selection_window='unknown';
  const wrapper=mount(LiveAvailabilityGrid,{props:{grid:data}});expect(wrapper.findAll('.observation-cell').every(button=>button.element.disabled)).toBe(true);
 });
});
