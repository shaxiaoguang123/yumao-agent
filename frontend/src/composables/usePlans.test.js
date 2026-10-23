import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils';
import { defineComponent, reactive, ref } from 'vue';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { usePlans } from './usePlans.js';
import { context, intent, plan, windowState } from '../components/plans/testFixtures.js';

enableAutoUnmount(afterEach);

function setup(overrides={}) {
  const api={list:vi.fn(async()=>({plans:[]})),options:vi.fn(async()=>({context})),window:vi.fn(async()=>windowState),...overrides};
  const session=reactive({status:'authenticated',user:{user_id:'owner'},csrfToken:'csrf',invalidationEpoch:0});
  const credential=ref('credential-a');let state;
  const wrapper=mount(defineComponent({setup(){state=usePlans(api,session,()=>credential.value,{requireCredential:true});return{};},template:'<div />'}));
  return {api,session,credential,state,wrapper};
}

describe('shared plan metadata and credential isolation',()=>{
  it('keeps pending shared metadata across Token changes while refreshing owned plans',async()=>{
    let finish;
    const {api,credential,state}=setup({options:vi.fn(()=>new Promise(resolve=>{finish=resolve;}))});
    credential.value='credential-b';await flushPromises();finish({context});await flushPromises();
    expect(api.options).toHaveBeenCalledOnce();expect(api.window).toHaveBeenCalledOnce();
    expect(api.list.mock.calls).toEqual([['credential-a'],['credential-b']]);
    expect(state.context.value).toEqual(context);expect(state.defaultWindow.value).toEqual(windowState);
  });
  it('does not apply a late save from the previous Token to the new Token',async()=>{
    let finish;
    const {credential,state}=setup({create:vi.fn(()=>new Promise(resolve=>{finish=resolve;}))});await flushPromises();
    state.startNew();const saving=state.save(intent);credential.value='credential-b';await flushPromises();
    finish({plan:plan(1,{credential_id:'credential-a'})});await saving;
    expect(state.plans.value).toEqual([]);expect(state.source.value).toBeNull();expect(state.saving.value).toBe(false);
  });
});
