import { mount,flushPromises,enableAutoUnmount } from '@vue/test-utils';
import { reactive } from 'vue';
import { createRouter,createMemoryHistory } from 'vue-router';
import { describe,it,expect,vi,afterEach } from 'vitest';
import LoginView from './LoginView.vue';
enableAutoUnmount(afterEach);
async function loginView(login){const router=createRouter({history:createMemoryHistory(),routes:[{path:'/login',name:'login',component:{template:'<div/>'}},{path:'/',name:'home',component:{template:'<div/>'}},{path:'/register',name:'register',component:{template:'<div/>'}}]});await router.push('/login');const wrapper=mount(LoginView,{global:{plugins:[router],provide:{sessionStore:reactive({login,errorMessage:'用户名或密码错误'})}}});await wrapper.get('input[name=username]').setValue('synthetic-user');await wrapper.get('input[name=password]').setValue('synthetic-password');return wrapper;}
describe('login form lifecycle',()=>{
 it('locks duplicate form submissions while pending and recovers after a rejected login',async()=>{let resolve;const login=vi.fn(()=>new Promise(r=>{resolve=r;}));const wrapper=await loginView(login);await wrapper.get('form').trigger('submit');await wrapper.get('form').trigger('submit');expect(login).toHaveBeenCalledOnce();expect(wrapper.get('button').element.disabled).toBe(true);resolve(false);await flushPromises();expect(wrapper.get('button').element.disabled).toBe(false);expect(wrapper.get('[role=alert]').text()).toBe('用户名或密码错误');});
 it('uses safe feedback and unlocks after an unexpected client rejection',async()=>{const wrapper=await loginView(vi.fn().mockRejectedValue(new Error('synthetic-private-detail')));await wrapper.get('form').trigger('submit');await flushPromises();expect(wrapper.get('[role=alert]').text()).toBe('登录暂不可用，请重试');expect(wrapper.get('button').element.disabled).toBe(false);expect(wrapper.text()).not.toContain('synthetic-private-detail');});
});
