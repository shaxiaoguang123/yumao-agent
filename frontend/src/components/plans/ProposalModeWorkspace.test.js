import { defineComponent } from 'vue';
import { mount } from '@vue/test-utils';
import { describe, expect, it } from 'vitest';
import ProposalModeWorkspace from './ProposalModeWorkspace.vue';

const QueueAssistant=defineComponent({name:'ProposalAssistant',template:'<div data-testid="queue-assistant">队列模式</div>'});
const IntentAssistant=defineComponent({name:'IntentPlanAssistant',template:'<div data-testid="intent-assistant">计划编辑模式</div>'});

describe('proposal mode workspace',()=>{
 it('keeps queue drafting and existing-plan editing as separate chat modes',async()=>{
  const wrapper=mount(ProposalModeWorkspace,{
   props:{planApi:{},proposalApi:{},intentProposalApi:{},session:{status:'authenticated',user:{user_id:'u'}}},
   global:{stubs:{ProposalAssistant:QueueAssistant,IntentPlanAssistant:IntentAssistant}},
  });
  expect(wrapper.get('[data-testid="queue-assistant"]').isVisible()).toBe(true);
  expect(wrapper.find('[data-testid="intent-assistant"]').exists()).toBe(false);
  await wrapper.get('[data-testid="proposal-mode-edit"]').trigger('click');
  expect(wrapper.get('[data-testid="proposal-mode-edit"]').attributes('aria-pressed')).toBe('true');
  expect(wrapper.find('[data-testid="queue-assistant"]').exists()).toBe(false);
  expect(wrapper.get('[data-testid="intent-assistant"]').isVisible()).toBe(true);
  await wrapper.get('[data-testid="proposal-mode-queue"]').trigger('click');
  expect(wrapper.get('[data-testid="queue-assistant"]').isVisible()).toBe(true);
  expect(wrapper.find('[data-testid="intent-assistant"]').exists()).toBe(false);
 });
});
