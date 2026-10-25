import { enableAutoUnmount, mount } from '@vue/test-utils';
import { afterEach, describe, expect, it, vi } from 'vitest';
import ThemeSwitcher from './ThemeSwitcher.vue';
import { applyThemePreference, readThemePreference } from '../utils/theme.js';

enableAutoUnmount(afterEach);
afterEach(()=>{vi.restoreAllMocks();localStorage.clear();delete document.documentElement.dataset.theme;document.head.innerHTML='';});
describe('appearance preference',()=>{
 it('selects explicit themes, restores them and returns to the system',async()=>{
  document.head.innerHTML='<meta name="theme-color" media="(prefers-color-scheme: light)"><meta name="theme-color" media="(prefers-color-scheme: dark)">';
  const wrapper=mount(ThemeSwitcher);
  for(const value of ['dark','light']){
   await wrapper.get(`input[value="${value}"]`).setValue(true);
   expect(document.documentElement.dataset.theme).toBe(value);
   expect(readThemePreference()).toBe(value);
   expect([...document.querySelectorAll('meta')].map(n=>n.content)).toEqual([value==='dark'?'#000000':'#f5f5f7',value==='dark'?'#000000':'#f5f5f7']);
  }
  wrapper.unmount();expect(mount(ThemeSwitcher).get('input[value="light"]').element.checked).toBe(true);
  applyThemePreference('system',{persist:true});expect(localStorage.length).toBe(0);
  expect([...document.querySelectorAll('meta')].map(n=>n.content)).toEqual(['#f5f5f7','#000000']);
 });
 it('synchronizes a preference changed in another tab and handles storage clear',async()=>{
  const wrapper=mount(ThemeSwitcher);
  localStorage.setItem('yumao-theme','dark');window.dispatchEvent(new StorageEvent('storage',{key:'yumao-theme'}));
  await wrapper.vm.$nextTick();expect(wrapper.get('input[value="dark"]').element.checked).toBe(true);
  localStorage.clear();window.dispatchEvent(new StorageEvent('storage',{key:null}));await wrapper.vm.$nextTick();
  expect(wrapper.get('input[value="system"]').element.checked).toBe(true);
  localStorage.setItem('yumao-theme','garbage');expect(readThemePreference()).toBe('system');
 });
 it('still switches in memory when storage is blocked',async()=>{
  vi.spyOn(Storage.prototype,'getItem').mockImplementation(()=>{throw Error('blocked');});
  vi.spyOn(Storage.prototype,'setItem').mockImplementation(()=>{throw Error('blocked');});
  const wrapper=mount(ThemeSwitcher);await wrapper.get('input[value="dark"]').setValue(true);
  expect(document.documentElement.dataset.theme).toBe('dark');
  wrapper.get('details').element.open=true;await wrapper.get('summary').trigger('keydown',{key:'Escape'});
  expect(wrapper.get('details').element.open).toBe(false);
 });
});
