import { flushPromises, mount } from '@vue/test-utils';
import { describe, expect, it, vi } from 'vitest';
import PlanForm from './PlanForm.vue';
import VenueTimeGrid from './VenueTimeGrid.vue';
import { context, intent } from './testFixtures.js';

function gridReply() {
  const cell={state:'selectable',selectable:true,reason_code:'synthetic_selectable',category_label:null};
  return {
    grid_version:'venue-time-grid-v2',simulation:true,
    source:{source:'synthetic-v1:partially_occupied',simulation:true,data_state:'synthetic',trust_state:'synthetic'},
    scenario:'partially_occupied',notice:'合成预览，不是实时库存。',target_date:intent.target_date,
    timezone_name:context.timezone_name,venue:{display_name:intent.venue_preference,verification:'unverified_manual'},
    atom_minutes:30,duration_minutes:60,
    courts:[{display_name:'6号场',verification:'unverified_manual'},{display_name:'5号场',verification:'unverified_manual'}],
    rows:[
      {start_time:'18:00',end_time:'18:30',cells:[cell,{...cell}]},
      {start_time:'18:30',end_time:'19:00',cells:[cell,{...cell}]},
    ],can_query_upstream:false,can_book:false,can_pay:false,can_create_job:false,
  };
}

async function mountForm(timeRange={start:'18:00',end:'20:00'}) {
  const source={planId:'plan-a',baseVersion:2,intent:{
    ...structuredClone(intent),court_preferences:['6号场','5号场'],duration_minutes:60,preferred_start_times:['18:00','19:00'],
    fallback_policy:{allow_any_court_in_venue:true,allow_time_shift:true,allowed_start_time_range:timeRange},
  },context:structuredClone(context)};
  const gridApi={options:vi.fn(async()=>({grid_preview_enabled:true,grid_scenarios:[{id:'partially_occupied',name:'部分占用'}]})),gridPreview:vi.fn(async()=>gridReply())};
  const wrapper=mount(PlanForm,{props:{source,busy:false,saveBlocked:false,fields:{},gridApi}});
  await flushPromises();
  expect(wrapper.findComponent(VenueTimeGrid).props('venuePreference')).toBe(intent.venue_preference);
  expect(wrapper.findComponent(VenueTimeGrid).props('courtPreferences')).toEqual(['6号场','5号场']);
  expect(wrapper.findComponent(VenueTimeGrid).props('timezoneName')).toBe(context.timezone_name);
  await wrapper.get('[data-testid="grid-load"]').trigger('click');await flushPromises();
  await wrapper.get('[data-testid="grid-cell-0-1"]').trigger('click');
  await wrapper.get('[data-testid="grid-cell-1-1"]').trigger('click');
  await wrapper.get('[data-testid="grid-add-backup-0"]').trigger('click');
  await wrapper.get('[data-testid="grid-apply"]').trigger('click');
  return wrapper;
}

describe('grid selection review in the plan form',()=>{
  it('defaults to strict scope and saves only after explicit confirmation',async()=>{
    const wrapper=await mountForm();
    expect(wrapper.text()).toContain('原来允许同场馆其他场地：是');
    expect(wrapper.text()).toContain('原时间浮动：18:00～20:00');
    expect(wrapper.text()).toContain('拟保存不允许额外场地或时间浮动');
    expect(wrapper.text()).toContain('价格上限保持不变');
    expect(wrapper.emitted('save')).toBeUndefined();
    await wrapper.get('[data-testid="confirm-grid-selection"]').trigger('click');
    expect(wrapper.emitted('save')).toBeUndefined();
    await wrapper.get('form').trigger('submit');
    expect(wrapper.emitted('save')[0][0]).toMatchObject({
      target_date:intent.target_date,preferred_start_times:['18:00'],duration_minutes:60,
      court_preferences:['5号场','6号场'],
      fallback_policy:{allow_any_court_in_venue:false,allow_time_shift:false,allowed_start_time_range:null},
      price_ceiling_minor:intent.price_ceiling_minor,
    });
  });

  it('retains broader fallback only after the user chooses that preview mode',async()=>{
    const wrapper=await mountForm();
    await wrapper.get('[data-testid="grid-mode-preserve"]').setValue();
    expect(wrapper.text()).toContain('拟保存保留原备用策略');
    await wrapper.get('[data-testid="confirm-grid-selection"]').trigger('click');
    await wrapper.get('form').trigger('submit');
    expect(wrapper.emitted('save')[0][0].fallback_policy).toEqual({
      allow_any_court_in_venue:true,allow_time_shift:true,
      allowed_start_time_range:{start:'18:00',end:'20:00'},
    });
  });

  it('blocks retaining a time-shift range that excludes the selected grid start',async()=>{
    const wrapper=await mountForm({start:'19:00',end:'20:00'});
    expect(wrapper.get('[data-testid="grid-mode-preserve"]').element.disabled).toBe(true);
    expect(wrapper.text()).toContain('18:00 不在原时间浮动范围 19:00～20:00 内');
    await wrapper.get('[data-testid="confirm-grid-selection"]').trigger('click');
    await wrapper.get('form').trigger('submit');
    expect(wrapper.emitted('save')[0][0].fallback_policy).toEqual({
      allow_any_court_in_venue:false,allow_time_shift:false,allowed_start_time_range:null,
    });
  });

  it('cancels the preview without changing form values and invalidates it on later edits',async()=>{
    const wrapper=await mountForm();
    await wrapper.get('[data-testid="cancel-grid-selection"]').trigger('click');
    expect(wrapper.find('[data-testid="grid-apply-confirmation"]').exists()).toBe(false);
    await wrapper.get('[data-testid="grid-apply"]').trigger('click');
    expect(wrapper.find('[data-testid="grid-apply-confirmation"]').exists()).toBe(true);
    await wrapper.get('#plan-venue_preference').setValue('新的人工场馆偏好');
    expect(wrapper.find('[data-testid="grid-apply-confirmation"]').exists()).toBe(false);
    expect(wrapper.text()).toContain('表单内容已变化，请重新生成并确认网格选择');
  });

  it('keeps applied fields but discards old grid state when a version conflict blocks saving',async()=>{
    const wrapper=await mountForm();
    await wrapper.get('[data-testid="confirm-grid-selection"]').trigger('click');
    expect(wrapper.get('[name="start_time_0"]').element.value).toBe('18:00');
    await wrapper.setProps({saveBlocked:true});
    expect(wrapper.find('[data-testid="grid-cell-0-1"]').exists()).toBe(false);
    expect(wrapper.get('[name="start_time_0"]').element.value).toBe('18:00');
    expect(wrapper.get('[data-testid="save-plan"]').element.disabled).toBe(true);
    expect(wrapper.text()).toContain('预约意向字段或计划/会话上下文已变化');
  });
});
