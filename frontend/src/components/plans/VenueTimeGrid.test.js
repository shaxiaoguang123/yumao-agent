import { flushPromises, mount, enableAutoUnmount } from '@vue/test-utils';
import { afterEach, describe, expect, it, vi } from 'vitest';
import VenueTimeGrid from './VenueTimeGrid.vue';

enableAutoUnmount(afterEach);

function cell(state='selectable') {
  return {state,selectable:state==='selectable',reason_code:`synthetic_${state}`,category_label:state==='activity_occupied'?'示例活动':null};
}
function grid(changes={}) {
  return {
    grid_version:'venue-time-grid-v2',
    simulation:true,
    source:{source:'synthetic-v1:partially_occupied',simulation:true,data_state:'synthetic',trust_state:'synthetic'},
    scenario:'partially_occupied',
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
function threeCourtGrid(){
  const result=grid();result.courts.push({display_name:'4号场',verification:'unverified_manual'});
  result.rows=result.rows.map(row=>({...row,cells:[...row.cells,cell()]}));return result;
}
function apiFixture(overrides={}) {
  return {options:vi.fn(async()=>({grid_preview_enabled:true,grid_scenarios:[{id:'partially_occupied',name:'部分占用'}]})),gridPreview:vi.fn(async()=>grid()),...overrides};
}
async function setup(api=apiFixture(),props={}) {
  const wrapper=mount(VenueTimeGrid,{props:{api,targetDate:'2026-10-20',durationMinutes:60,venuePreference:'人工输入场馆',courtPreferences:['6号场','5号场'],timezoneName:'Asia/Shanghai',...props}});
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

  it('keeps the first selected court as primary and adds alternatives only by explicit action',async()=>{
    const {wrapper,api}=await setup();await load(wrapper);
    await wrapper.get('[data-testid="grid-cell-0-1"]').trigger('click');
    await wrapper.get('[data-testid="grid-cell-1-1"]').trigger('click');
    expect(wrapper.text()).toContain('首选场地：5号场');
    expect(wrapper.get('[data-testid="grid-cell-0-1"]').attributes('aria-pressed')).toBe('true');
    expect(wrapper.get('[data-testid="grid-apply"]').element.disabled).toBe(false);
    await wrapper.get('[data-testid="grid-cell-0-0"]').trigger('click');
    expect(wrapper.get('[data-testid="grid-cell-0-0"]').attributes('aria-pressed')).toBe('false');
    expect(wrapper.text()).toContain('其他场地请使用下方“添加为备选场地”');
    await wrapper.get('[data-testid="grid-clear"]').trigger('click');

    for(const id of ['grid-cell-0-1','grid-cell-1-1']) await wrapper.get(`[data-testid="${id}"]`).trigger('click');
    expect(wrapper.text()).toContain('18:00～19:00');
    expect(wrapper.text()).toContain('首选场地：5号场');
    await wrapper.get('[data-testid="grid-add-backup-0"]').trigger('click');
    expect(wrapper.text()).toContain('备选 1：6号场');
    expect(wrapper.text()).toContain('只按顺序尝试一个场地，不代表同时预约多块场地');
    await wrapper.get('[data-testid="grid-promote-backup-0"]').trigger('click');
    expect(wrapper.text()).toContain('首选场地：6号场');
    expect(wrapper.text()).toContain('备选 1：5号场');
    expect(wrapper.get('[data-testid="grid-apply"]').element.disabled).toBe(false);
    await wrapper.get('[data-testid="grid-apply"]').trigger('click');
    expect(wrapper.emitted('apply')[0][0]).toEqual({target_date:'2026-10-20',start_time:'18:00',end_time:'19:00',duration_minutes:60,court_preferences:['6号场','5号场'],scenario:'partially_occupied'});
    expect(api.gridPreview.mock.calls[0][0]).toEqual({target_date:'2026-10-20',duration_minutes:60,venue_preference:'人工输入场馆',court_preferences:['6号场','5号场'],scenario:'partially_occupied'});
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
    await wrapper.get('[data-testid="grid-cell-0-0"]').trigger('click');
    await wrapper.get('[data-testid="grid-cell-1-0"]').trigger('click');
    expect(wrapper.get('[data-testid="grid-add-backup-1"]').element.disabled).toBe(false);
    await wrapper.get('[data-testid="grid-add-backup-1"]').trigger('click');
    expect(wrapper.text()).toContain('备选 1：5号场');
    expect(wrapper.find('[data-testid="grid-cell-0-1"]').attributes('aria-pressed')).toBe('false');
    await wrapper.get('[data-testid="grid-remove-backup-0"]').trigger('click');
    expect(wrapper.text()).toContain('首选场地：6号场');
    expect(wrapper.text()).not.toContain('备选 1：5号场');
    expect(wrapper.get('[data-testid="grid-apply"]').element.disabled).toBe(false);
  });

  it('orders backups explicitly and removing one preserves the remaining preference',async()=>{
    const result=threeCourtGrid();
    const {wrapper}=await setup(apiFixture({gridPreview:vi.fn(async()=>result)}),{courtPreferences:['6号场','5号场','4号场']});
    await load(wrapper);
    await wrapper.get('[data-testid="grid-cell-0-1"]').trigger('click');
    await wrapper.get('[data-testid="grid-cell-1-1"]').trigger('click');
    await wrapper.get('[data-testid="grid-add-backup-0"]').trigger('click');
    await wrapper.get('[data-testid="grid-add-backup-2"]').trigger('click');
    expect(wrapper.text()).toContain('备选 1：6号场');expect(wrapper.text()).toContain('备选 2：4号场');
    await wrapper.get('[data-testid="grid-backup-down-0"]').trigger('click');
    expect(wrapper.text()).toContain('备选 1：4号场');expect(wrapper.text()).toContain('备选 2：6号场');
    await wrapper.get('[data-testid="grid-remove-backup-1"]').trigger('click');
    expect(wrapper.text()).toContain('首选场地：5号场');expect(wrapper.text()).toContain('备选 1：4号场');
    expect(wrapper.text()).not.toContain('备选 2：6号场');
  });

  it('does not add a backup unless every selected interval is selectable on that court',async()=>{
    const result=grid();result.rows[1].cells[0]=cell('activity_occupied');
    const {wrapper}=await setup(apiFixture({gridPreview:vi.fn(async()=>result)}));await load(wrapper);
    await wrapper.get('[data-testid="grid-cell-0-1"]').trigger('click');
    await wrapper.get('[data-testid="grid-cell-1-1"]').trigger('click');
    expect(wrapper.get('[data-testid="grid-add-backup-0"]').element.disabled).toBe(true);
    expect(wrapper.text()).not.toContain('备选 1：6号场');
  });

  it('does not treat adjacent rows with a real time gap as continuous',async()=>{
    const result=grid();result.rows[1]={...result.rows[1],start_time:'19:00',end_time:'19:30'};
    const {wrapper}=await setup(apiFixture({gridPreview:vi.fn(async()=>result)}));await load(wrapper);
    await wrapper.get('[data-testid="grid-cell-0-0"]').trigger('click');
    await wrapper.get('[data-testid="grid-cell-1-0"]').trigger('click');
    expect(wrapper.text()).toContain('实际时间不连续');
    expect(wrapper.get('[data-testid="grid-apply"]').element.disabled).toBe(true);
  });

  it('uses interval boundaries rather than assuming a permanent 30-minute atom',async()=>{
    const result=grid({atom_minutes:20,rows:[
      {start_time:'18:00',end_time:'18:20',cells:[cell(),cell()]},
      {start_time:'18:20',end_time:'18:40',cells:[cell(),cell()]},
      {start_time:'18:40',end_time:'19:00',cells:[cell(),cell()]},
    ]});
    const {wrapper}=await setup(apiFixture({gridPreview:vi.fn(async()=>result)}));await load(wrapper);
    for(const id of ['grid-cell-0-0','grid-cell-1-0','grid-cell-2-0']) await wrapper.get(`[data-testid="${id}"]`).trigger('click');
    expect(wrapper.text()).toContain('18:00～19:00 · 60 分钟');
    expect(wrapper.get('[data-testid="grid-apply"]').element.disabled).toBe(false);
  });

  it('clears a previously loaded grid when its plan/session context changes',async()=>{
    const {wrapper}=await setup();await load(wrapper);
    await wrapper.get('[data-testid="grid-cell-0-0"]').trigger('click');
    await wrapper.setProps({selectionContextKey:'plan-2:version-3:user-b'});
    expect(wrapper.find('[data-testid="grid-cell-0-0"]').exists()).toBe(false);
    expect(wrapper.text()).toContain('预约意向字段或计划/会话上下文已变化');
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
