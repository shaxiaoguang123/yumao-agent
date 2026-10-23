import { beforeEach, describe, expect, it } from 'vitest';
import { agentModelKey, agentModelWasRecentlyReady, rememberAgentModelReady } from './agentReadiness.js';

describe('recent Agent model checks', () => {
  beforeEach(() => rememberAgentModelReady('', '', 0));

  it('reuses a successful probe only for the same user and model for five minutes', () => {
    rememberAgentModelReady('user-a', 'model-a', 10_000);

    expect(agentModelWasRecentlyReady('user-a', 'model-a', 69_999)).toBe(true);
    expect(agentModelWasRecentlyReady('user-b', 'model-a', 69_999)).toBe(false);
    expect(agentModelWasRecentlyReady('user-a', 'model-b', 69_999)).toBe(false);
    expect(agentModelWasRecentlyReady('user-a', 'model-a', 309_999)).toBe(true);
    expect(agentModelWasRecentlyReady('user-a', 'model-a', 310_000)).toBe(false);
  });
  it('invalidates readiness after model edits, key rotation, login or Session invalidation', () => {
    const model={id:'m',version:1},session={csrfToken:'session-a',invalidationEpoch:0};
    const key=agentModelKey(model,session);rememberAgentModelReady('a',key);
    for(const changed of [agentModelKey({...model,version:2},session),agentModelKey(model,{...session,csrfToken:'session-b'}),agentModelKey(model,{...session,invalidationEpoch:1})])expect(agentModelWasRecentlyReady('a',changed)).toBe(false);
  });
});
