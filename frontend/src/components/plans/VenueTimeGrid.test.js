import { flushPromises, mount, enableAutoUnmount } from '@vue/test-utils';
import { afterEach, describe, expect, it, vi } from 'vitest';
import VenueTimeGrid from './VenueTimeGrid.vue';

enableAutoUnmount(afterEach);

function cell(state='selectable') {
  return {state,selectable:state==='selectable',reason_code:`synthetic_${state}`,category_label:state==='activity_occupied'?'示例活动':null};
}
function grid(changes={}) {
  return {
    grid_version:'venue-time-grid-v1',
    simulation:true,
    source:{source:'synthetic-grid-v1',data_state:'synthetic',trust_state:'synthetic'},
    notice:'合成网格预览，不是实时库存。',
    target_date:'2026-10-20',timezone_name:'Asia/Shanghai',
    venue:{display_name:'人工输入场馆',verification:'unverified_manual'},
    atom_minutes:30,duration_minutes:60,
    courts:[{display_name:'6号场',verification:'unverified_manual'},{display_name:'5号场',verification:'unverified_manual'}],
    rows:[
      {start_time:'18:00',end_time:'18:30',cells:[cell(),cell()]},
      {start_time:'18:30',end_time:'19:00',cells:[cell(),cell()]},
      {start_time:'19:00',end_time:'19:30',cells:[cell('reserved'),cell('activity_occupied')]},
      {start_time:'19:30',end_time:'20:00',cells:[cell('unbookable'),cell('unknown')]},
      {start_time:'20:00',end_time:'20:30',cells:[cell(),cell()]},
      {start_time:'20:30',end_time:'21:00',cells:[cell(),cell()]},
    ],
    can_query_upstream:false,can_book:false,can_pay:false,can_create_job:false,
    ...changes,
  };
}
function apiFixture(overrides={}) {
  return {options:vi.fn(async()=>({grid_preview_enabled:true})),gridPreview:vi.fn(async()=>grid()),...overrides};
}
async function setup(api=apiFixture(),props={}) {
  const wrapper=mount(VenueTimeGrid,{props:{api,targetDate:'2026-10-20',durationMinutes:60,venuePreference:'人工输入场馆',courtPreferences:['6号场','5号场'],...props}});
  await flushPromises();
  return {wrapper,api};
}
async function load(wrapper) {await wrapper.get('[data-testid="grid-load"]').trigger('click');await flushPromises();}

describe('synthetic venue-time preference grid',()=>{
  it('shows source warning and makes reserved, activity, unbookable and unknown cells unavailable',async()=>{
    const {wrapper}=await setup();await load(wrapper);
    expect(wrapper.text()).toContain('合成网格预览，不是实时库存');
    expect(wrapper.get('[data-testid="grid-cell-0-0"]').element.disabled).toBe(false);
    for(const id of ['grid-cell-2-0','grid-cell-2-1','grid-cell-3-0','grid-cell-3-1'])
      expect(wrapper.get(`[data-testid="${id}"]`).element.disabled).toBe(true);
    expect(wrapper.text()).toContain('已预订（合成）');
    expect(wrapper.text()).toContain('活动占用（合成）');
    expect(wrapper.text()).toContain('未知');
  });

  it('allows deselection and applies only a complete contiguous same-time block',async()=>{
    const {wrapper,api}=await setup();await load(wrapper);
    await wrapper.get('[data-testid="grid-cell-0-0"]').trigger('click');
    expect(wrapper.get('[data-testid="grid-cell-0-0"]').attributes('aria-pressed')).toBe('true');
    expect(wrapper.get('[data-testid="grid-apply"]').element.disabled).toBe(true);
    await wrapper.get('[data-testid="grid-cell-0-0"]').trigger('click');
    expect(wrapper.get('[data-testid="grid-cell-0-0"]').attributes('aria-pressed')).toBe('false');

    await wrapper.get('[data-testid="grid-cell-0-0"]').trigger('click');
    await wrapper.get('[data-testid="grid-cell-2-0"]').trigger('click');
    expect(wrapper.text()).toContain('每个候选场地需选择连续的 2 个时间格');
    expect(wrapper.get('[data-testid="grid-apply"]').element.disabled).toBe(true);

    await wrapper.get('[data-testid="grid-clear"]').trigger('click');
    for(const id of ['grid-cell-0-0','grid-cell-1-0','grid-cell-0-1','grid-cell-1-1'])
      await wrapper.get(`[data-testid="${id}"]`).trigger('click');
    expect(wrapper.text()).toContain('18:00～19:00');
    expect(wrapper.get('[data-testid="grid-apply"]').element.disabled).toBe(false);
    await wrapper.get('[data-testid="grid-apply"]').trigger('click');
    expect(wrapper.emitted('apply')[0][0]).toEqual({target_date:'2026-10-20',start_time:'18:00',duration_minutes:60,court_preferences:['6号场','5号场']});
    expect(api.gridPreview.mock.calls[0][0]).toEqual({target_date:'2026-10-20',duration_minutes:60,venue_preference:'人工输入场馆',court_preferences:['6号场','5号场']});
  });

  it('clears selection and loaded cells when the date changes',async()=>{
    const {wrapper,api}=await setup();await load(wrapper);await wrapper.get('[data-testid="grid-cell-0-0"]').trigger('click');
    await wrapper.get('[data-testid="grid-date"]').setValue('2026-10-21');
    expect(wrapper.emitted('update:targetDate').at(-1)[0]).toBe('2026-10-21');
    await wrapper.setProps({targetDate:'2026-10-21'});await flushPromises();
    expect(wrapper.find('[data-testid="grid-cell-0-0"]').exists()).toBe(false);
    expect(api.gridPreview).toHaveBeenCalledOnce();
  });

  it('does not expand mismatched court/time cells into an unintended Cartesian preference',async()=>{
    const {wrapper}=await setup();await load(wrapper);
    for(const id of ['grid-cell-0-0','grid-cell-1-0','grid-cell-4-1','grid-cell-5-1'])
      await wrapper.get(`[data-testid="${id}"]`).trigger('click');
    expect(wrapper.text()).toContain('多个场地必须选择完全相同的连续时间段');
    expect(wrapper.get('[data-testid="grid-apply"]').element.disabled).toBe(true);
  });

  it('keeps manual planning usable when grid preview is disabled or fails',async()=>{
    const disabled=await setup(apiFixture({options:vi.fn(async()=>({grid_preview_enabled:false}))}));
    expect(disabled.wrapper.text()).toContain('当前环境未启用模拟网格');
    expect(disabled.wrapper.find('[data-testid="grid-load"]').exists()).toBe(false);
    const failed=await setup(apiFixture({gridPreview:vi.fn(async()=>{throw new Error('synthetic failure');})}));
    await load(failed.wrapper);expect(failed.wrapper.text()).toContain('合成网格读取失败');
  });

  it('rejects a source mismatch or any execution capability',async()=>{
    const wrongDate=await setup(apiFixture({gridPreview:vi.fn(async()=>grid({target_date:'2026-10-21'}))}));
    await load(wrongDate.wrapper);expect(wrongDate.wrapper.text()).toContain('网格数据与当前表单不一致');
    const unsafe=grid({can_book:true});
    const flagged=await setup(apiFixture({gridPreview:vi.fn(async()=>unsafe)}));
    await load(flagged.wrapper);expect(flagged.wrapper.text()).toContain('已停止展示');
  });
});
