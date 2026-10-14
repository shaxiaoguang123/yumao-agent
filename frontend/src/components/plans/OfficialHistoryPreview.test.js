import { flushPromises, mount, enableAutoUnmount } from '@vue/test-utils';
import { afterEach, describe, expect, it, vi } from 'vitest';
import OfficialHistoryPreview from './OfficialHistoryPreview.vue';

enableAutoUnmount(afterEach);

function preview() {
  const cell=(state)=>({state:`historical_${state}`,selectable:false,reason_code:'historical_unverified',category_label:null});
  return {
    grid_version:'official-history-grid-v1',simulation:false,
    source:{source:'official-bookingByTime-history',data_state:'historical_unverified',trust_state:'normalized_unverified',freshness_state:'unknown',captured_at_utc_ms:null},
    notice:'只读历史显示。',target_date:null,timezone_name:null,
    venue:{display_name:'场馆查询范围未知',verification:'unverified'},
    courts:[{display_name:'合成场地甲',verification:'historical_unverified'},{display_name:'合成场地乙',verification:'historical_unverified'}],
    rows:[{time_label:'18:00',time_status:{state:'recognized_unverified',code:'1'},cells:[cell('selectable'),cell('reserved')]},
      {time_label:'18:30',time_status:{state:'unknown',code:null},cells:[cell('unknown'),cell('unknown')]}],
    price_state:'omitted_unit_unverified',can_select:false,can_match:false,can_bind:false,
    can_query_upstream:false,can_book:false,can_pay:false,can_create_job:false,
  };
}

function envelope(){return {success:true,message:'synthetic',resultData:{stepnumber:'1',nodeList:[{nodeid:'private-node',sitename:'合成场地甲'}],timeList:[{time:'18:00',status:'1'}],conflictList:[],priceList:[{x:'0',y:'0',price:'private-price'}]}};}

describe('official history preview',()=>{
  it('parses an explicitly selected local response and renders a non-interactive historical grid',async()=>{
    const api={options:vi.fn(async()=>({history_preview_enabled:true})),historyPreview:vi.fn(async()=>preview())};
    const wrapper=mount(OfficialHistoryPreview,{props:{api,session:{status:'authenticated',user:{user_id:'user-a'},csrfToken:'csrf-a'}}});
    await flushPromises();
    expect(api.historyPreview).not.toHaveBeenCalled();
    const file=new File([JSON.stringify(envelope())],'local-response.json',{type:'application/json'});
    const input=wrapper.get('[data-testid="history-response-file"]');
    Object.defineProperty(input.element,'files',{value:[file],configurable:true});
    await input.trigger('change');await flushPromises();
    expect(api.historyPreview).toHaveBeenCalledWith(envelope());
    expect(wrapper.text()).toContain('历史客户端显示可选（非实时）');
    expect(wrapper.text()).toContain('行标记未知');
    expect(wrapper.text()).toContain('场馆查询范围未知');
    expect(wrapper.text()).toContain('价格单位未核验并已隐藏');
    expect(wrapper.text()).not.toContain('private-node');
    expect(wrapper.text()).not.toContain('private-price');
    expect(wrapper.find('button').exists()).toBe(false);
    expect(wrapper.text()).not.toContain('立即预约');
  });

  it('does not submit malformed local JSON or display raw contents',async()=>{
    const api={options:vi.fn(async()=>({history_preview_enabled:true})),historyPreview:vi.fn()};
    const wrapper=mount(OfficialHistoryPreview,{props:{api,session:{status:'authenticated',user:{user_id:'user-a'},csrfToken:'csrf-a'}}});
    await flushPromises();
    const file=new File(['private raw content'],'invalid.json',{type:'application/json'});
    const input=wrapper.get('[data-testid="history-response-file"]');
    Object.defineProperty(input.element,'files',{value:[file],configurable:true});
    await input.trigger('change');await flushPromises();
    expect(api.historyPreview).not.toHaveBeenCalled();
    expect(wrapper.text()).toContain('文件不是有效的 JSON 响应');
    expect(wrapper.text()).not.toContain('private raw content');
  });
});
