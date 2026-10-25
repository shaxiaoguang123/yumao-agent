import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils';
import { reactive } from 'vue';
import { afterEach, describe, expect, it, vi } from 'vitest';
import EmailNotificationSettings from './EmailNotificationSettings.vue';

enableAutoUnmount(afterEach);
const settings = (version=1, overrides={})=>({available:true,version,enabled:true,reminder_time:'20:00',result_time:'08:00',recipient:'notifications@example.test',worker_enabled:true,recent:[],...overrides});
const session = ()=>reactive({status:'authenticated',user:{user_id:'notification-owner'},csrfToken:'csrf',invalidationEpoch:0});

describe('EmailNotificationSettings',()=>{
  it('shows the verified recipient and saves the optional previous-evening reminder time',async()=>{
    const api={emailNotificationSettings:vi.fn(async()=>settings()),updateEmailNotificationSettings:vi.fn(async(version,value)=>settings(version+1,value)),sendEmailNotificationTest:vi.fn(async()=>({accepted:true}))};
    const wrapper=mount(EmailNotificationSettings,{props:{api,session:session()}});await flushPromises();
    expect(wrapper.text()).toContain('抢票前一晚提醒');expect(wrapper.text()).toContain('08:00');
    expect((await wrapper.get('input[type="email"]').attributes('readonly'))).toBeDefined();
    await wrapper.get('input[type="time"]').setValue('19:45');await wrapper.get('form').trigger('submit');await flushPromises();
    expect(api.updateEmailNotificationSettings).toHaveBeenCalledWith(1,{enabled:true,reminder_time:'19:45'});
    expect(wrapper.text()).toContain('邮箱通知已保存');
    await wrapper.get('button[type="button"]').trigger('click');await flushPromises();
    expect(api.sendEmailNotificationTest).toHaveBeenCalledOnce();
    expect(wrapper.text()).toContain('测试邮件已被 Cloudflare 接受');
  });

  it('hides notification controls for accounts that do not own the verified mailbox',async()=>{
    const api={emailNotificationSettings:vi.fn(async()=>({available:false})),updateEmailNotificationSettings:vi.fn(),sendEmailNotificationTest:vi.fn()};
    const wrapper=mount(EmailNotificationSettings,{props:{api,session:session()}});await flushPromises();
    expect(wrapper.find('section').exists()).toBe(false);expect(api.updateEmailNotificationSettings).not.toHaveBeenCalled();
    expect(api.sendEmailNotificationTest).not.toHaveBeenCalled();
  });

  it('discloses a save conflict without applying stale settings',async()=>{
    const api={emailNotificationSettings:vi.fn(async()=>settings()),updateEmailNotificationSettings:vi.fn(async()=>{throw Object.assign(new Error(),{status:409});})};
    const wrapper=mount(EmailNotificationSettings,{props:{api,session:session()}});await flushPromises();
    await wrapper.get('form').trigger('submit');await flushPromises();
    expect(wrapper.text()).toContain('设置已在其他页面更新');
  });

  it('does not expose a late response after logout',async()=>{
    let finish;const account=session();
    const api={emailNotificationSettings:vi.fn(()=>new Promise(resolve=>{finish=resolve;})),updateEmailNotificationSettings:vi.fn()};
    const wrapper=mount(EmailNotificationSettings,{props:{api,session:account}});
    account.status='unauthenticated';await flushPromises();finish(settings());await flushPromises();
    expect(wrapper.find('section').exists()).toBe(false);
  });

  it('shows a safe sender-domain hint from Cloudflare without exposing provider details',async()=>{
    const api={emailNotificationSettings:vi.fn(async()=>settings()),sendEmailNotificationTest:vi.fn(async()=>{throw Object.assign(new Error('private provider message'),{code:'cloudflare_e_sender_domain_not_available'});}),updateEmailNotificationSettings:vi.fn()};
    const wrapper=mount(EmailNotificationSettings,{props:{api,session:session()}});await flushPromises();
    await wrapper.get('button[type="button"]').trigger('click');await flushPromises();
    expect(wrapper.text()).toContain('Cloudflare 尚未为发件域启用邮件服务');
    expect(wrapper.text()).not.toContain('private provider message');
  });

  it('shows a safe account-plan hint from Cloudflare error codes',async()=>{
    const api={emailNotificationSettings:vi.fn(async()=>settings()),sendEmailNotificationTest:vi.fn(async()=>{throw Object.assign(new Error('provider error'),{code:'cloudflare_plan_required'});}),updateEmailNotificationSettings:vi.fn()};
    const wrapper=mount(EmailNotificationSettings,{props:{api,session:session()}});await flushPromises();
    await wrapper.get('button[type="button"]').trigger('click');await flushPromises();
    expect(wrapper.text()).toContain('Cloudflare Email Sending 报告当前账户需要 Workers Paid');
    expect(wrapper.text()).not.toContain('provider error');
  });
});
