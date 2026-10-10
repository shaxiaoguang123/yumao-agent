import { flushPromises, mount } from '@vue/test-utils';
import { reactive } from 'vue';
import { createRouter, createMemoryHistory } from 'vue-router';
import { afterEach, describe, it, expect, vi } from 'vitest';
import { enableAutoUnmount } from '@vue/test-utils';
import HomeView from './HomeView.vue';
enableAutoUnmount(afterEach);
async function home(list) {
 const router = createRouter({ history:createMemoryHistory(), routes:[{path:'/',name:'home',component:{template:'<div/>'}},{path:'/credentials',name:'credentials',component:{template:'<div/>'}},{path:'/account',name:'account',component:{template:'<div/>'}}] });
 await router.push('/');
 const wrapper=mount(HomeView,{global:{plugins:[router],provide:{sessionStore:reactive({status:'authenticated',user:{username:'Synthetic User'}}),credentialApi:{list}}}});
 await flushPromises(); return wrapper;
}
describe('dashboard credential overview',()=>{
 it('derives counts from actual records without presenting booking capability',async()=>{
  const wrapper=await home(vi.fn().mockResolvedValue({credentials:[{enabled:true,expiry_state:'expiry_ok',account_binding_state:'confirmed',last_confirmed_validation_state:'confirmed_valid'},{enabled:false,expiry_state:'expired',account_binding_state:'needs_reconfirmation',last_confirmed_validation_state:'confirmed_invalid'}]}));
  expect(wrapper.get('[data-testid="total-credentials"]').text()).toBe('2');
  expect(wrapper.get('[data-testid="enabled-credentials"]').text()).toBe('1');
  expect(wrapper.get('[data-testid="attention-credentials"]').text()).toBe('1');
  expect(wrapper.text()).toContain('尚未开放');
  expect(wrapper.find('button[data-testid="start-booking"]').exists()).toBe(false);
 });
 it('does not claim zero or a healthy state while the request is pending',async()=>{
  const wrapper=await home(()=>new Promise(()=>{}));
  expect(wrapper.get('[data-testid="total-credentials"]').text()).toBe('—');
  expect(wrapper.text()).toContain('正在读取凭据状态');
 });
 it('retries an unavailable overview and only then displays the genuine empty state',async()=>{
  const list=vi.fn().mockRejectedValueOnce(new Error('synthetic')).mockResolvedValueOnce({credentials:[]});
  const wrapper=await home(list);
  expect(wrapper.get('[data-testid="total-credentials"]').text()).toBe('—');
  expect(wrapper.text()).not.toContain('尚未添加预约凭据');
  await wrapper.get('[data-testid="retry-summary"]').trigger('click'); await flushPromises();
  expect(list).toHaveBeenCalledTimes(2);
  expect(wrapper.get('[data-testid="total-credentials"]').text()).toBe('0');
  expect(wrapper.text()).toContain('尚未添加预约凭据');
 });
});
