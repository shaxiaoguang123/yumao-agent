import { beforeEach, describe, expect, it } from 'vitest';
import { agentModelWasRecentlyReady, rememberAgentModelReady } from './agentReadiness.js';

describe('recent Agent model checks', () => {
  beforeEach(() => rememberAgentModelReady('', '', 0));

  it('reuses a successful probe only for the same user and model for one minute', () => {
    rememberAgentModelReady('user-a', 'model-a', 10_000);

    expect(agentModelWasRecentlyReady('user-a', 'model-a', 69_999)).toBe(true);
    expect(agentModelWasRecentlyReady('user-b', 'model-a', 69_999)).toBe(false);
    expect(agentModelWasRecentlyReady('user-a', 'model-b', 69_999)).toBe(false);
    expect(agentModelWasRecentlyReady('user-a', 'model-a', 70_000)).toBe(false);
  });
});
