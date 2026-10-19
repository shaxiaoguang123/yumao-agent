import { describe, expect, it } from 'vitest';
import { EVENTS, STATES, initialState, isLegal, legacyStatus, selectors, transition } from './proposalMachine.js';

const at = (name, extra = {}) => ({ ...initialState(), name, ...extra });
const run = (state, ...types) => types.reduce((s, type) => transition(s, { type }), state);

describe('proposal machine structure', () => {
  it('only ever moves to a declared state, and never mutates its input', () => {
    for (const name of STATES) {
      for (const type of EVENTS) {
        const before = Object.freeze({ ...at(name), conversation: null });
        const after = transition(before, { type, conversation: { phase: 'x' }, code: 'c' });
        expect(STATES).toContain(after.name);
        expect(before.name).toBe(name);
      }
    }
  });

  it('ignores every event that is not legal by returning the very same state', () => {
    for (const name of STATES) {
      for (const type of EVENTS) {
        const state = at(name);
        if (!isLegal(name, type)) expect(transition(state, { type })).toBe(state);
      }
    }
  });

  it('reaches every state from idle and can always get back to idle (except while a save is in flight)', () => {
    const seen = new Set(['idle']);
    const queue = [initialState()];
    while (queue.length) {
      const state = queue.shift();
      for (const type of EVENTS) {
        const next = transition(state, { type });
        const key = `${next.name}|${next.stale}|${next.verified}`;
        if (!seen.has(key)) {
          seen.add(key);
          queue.push(next);
        }
      }
    }
    const names = new Set([...seen].map((key) => key.split('|')[0]));
    for (const name of STATES) expect(names).toContain(name);
    for (const name of STATES.filter((n) => n !== 'saving')) {
      expect(run(at(name), 'RESTART').name).toBe('idle');
    }
  });

  it('has no transition that ends a request without an answer, failure, input change or restart', () => {
    for (const type of EVENTS) {
      const next = transition(at('generating'), { type });
      if (next.name !== 'generating') {
        expect(['ANSWER_NEEDS_INPUT', 'ANSWER_READY', 'ANSWER_UNSUPPORTED', 'ANSWER_ESCALATED', 'FAIL', 'INPUT_CHANGED', 'RESTART']).toContain(type);
      }
    }
  });
});

describe('guards that protect the user', () => {
  it('cannot save from anywhere but a fresh ready draft', () => {
    for (const name of STATES.filter((n) => n !== 'ready')) expect(transition(at(name), { type: 'SAVE' }).name).toBe(name);
    expect(transition(at('ready', { stale: true }), { type: 'SAVE' }).name).toBe('ready');
    expect(transition(at('ready'), { type: 'SAVE' }).name).toBe('saving');
  });

  it('cannot be interrupted while a save is in flight', () => {
    for (const type of ['INPUT_CHANGED', 'CANCEL', 'RESTART', 'SEND', 'SAVE']) {
      expect(transition(at('saving'), { type }).name).toBe('saving');
    }
  });

  it('turns a version conflict into a stale draft that must be reloaded before saving', () => {
    const stale = run(at('ready'), 'CONFLICT');
    expect(stale.stale).toBe(true);
    expect(selectors.canSave(stale)).toBe(false);
    expect(selectors.canSave(run(stale, 'SEND', 'ANSWER_READY'))).toBe(true);
    const conflict = run(at('saving'), 'SAVE_CONFLICT');
    expect([conflict.name, conflict.stale, conflict.errorCode]).toEqual(['ready', true, 'plan_version_conflict']);
  });

  it('keeps the draft after a definite rejection so nothing the user wrote is lost', () => {
    const rejected = transition(at('saving'), { type: 'SAVE_REJECTED', code: 'invalid_plan' });
    expect([rejected.name, rejected.errorCode]).toEqual(['ready', 'invalid_plan']);
  });

  it('keeps a draft stale when the plan changes mid-request, and clears it only by sending again', () => {
    let s = run(at('needs_input'), 'SEND', 'CONFLICT');
    expect([s.name, s.stale]).toEqual(['generating', true]);
    s = run(s, 'ANSWER_READY');
    expect([s.name, s.stale]).toEqual(['ready', true]);
    expect(selectors.canSave(s)).toBe(false);
    s = run(s, 'SEND');
    expect([s.name, s.stale]).toEqual(['generating', false]);
  });

  it('marks a draft stale when the plan changes during a follow-up, in every state that holds one', () => {
    for (const name of ['idle', 'generating', 'needs_input', 'ready', 'error']) {
      expect(run(at(name), 'CONFLICT').stale, name).toBe(true);
    }
    for (const name of ['saved', 'unsupported', 'escalated', 'saving']) {
      expect(run(at(name), 'CONFLICT').stale, name).toBe(false);
    }
  });

  it('can regenerate from a ready draft or after an unsupported answer', () => {
    expect(run(at('ready'), 'SEND').name).toBe('generating');
    expect(run(at('unsupported'), 'SEND').name).toBe('generating');
  });

  it('forgets the old conversation on restart but keeps it through a failed request', () => {
    const conversation = { phase: 'collecting' };
    expect(run(at('needs_input', { conversation }), 'RESTART').conversation).toBeNull();
    expect(run(at('needs_input', { conversation }), 'SEND').conversation).toBe(conversation);
  });

  it('abandons an in-flight request when the description changes', () => {
    expect(run(at('generating'), 'INPUT_CHANGED').name).toBe('idle');
  });

  it('keeps the escalated hand-off from being answered', () => {
    expect(selectors.composerLocked(at('escalated'))).toBe(true);
    expect(run(at('escalated'), 'SEND').name).toBe('escalated');
    expect(run(at('escalated'), 'INPUT_CHANGED').name).toBe('idle');
  });

  it('lets a failed request be retried without losing the conversation', () => {
    const failed = transition(at('generating', { conversation: { phase: 'collecting' } }), { type: 'FAIL', code: 'provider_timeout' });
    expect([failed.name, failed.errorCode, failed.conversation.phase]).toEqual(['error', 'provider_timeout', 'collecting']);
    expect(run(failed, 'SEND').name).toBe('generating');
  });
});

describe('walks through the whole conversation', () => {
  it('goes from a vague request to a saved draft', () => {
    let s = run(initialState(), 'SEND');
    s = transition(s, { type: 'ANSWER_NEEDS_INPUT', conversation: { phase: 'collecting' } });
    expect([s.name, s.conversation.phase]).toEqual(['needs_input', 'collecting']);
    s = run(s, 'SEND');
    s = run(s, 'ANSWER_READY');
    s = run(s, 'SAVE', 'SAVE_OK');
    expect(s.name).toBe('saved');
    expect(s.conversation).toBeNull();
    expect(selectors.terminal(s)).toBe(true);
  });

  it('ends in the manual hand-off when the server escalates', () => {
    let s = run(initialState(), 'SEND');
    s = transition(s, { type: 'ANSWER_ESCALATED', conversation: { escalation: { kind: 'stalled' } } });
    expect(s.name).toBe('escalated');
    expect(s.conversation.escalation.kind).toBe('stalled');
    expect(legacyStatus(s)).toBe('needs_input');
  });

  it('allows a new conversation right after a save', () => {
    const s = run(at('saved'), 'SEND');
    expect(s.name).toBe('generating');
  });
});

describe('what the existing components see', () => {
  it('maps the richer states onto the statuses they already render', () => {
    expect(STATES.map((name) => legacyStatus(at(name)))).toEqual(
      ['idle', 'generating', 'needs_input', 'ready', 'ready', 'saved', 'unsupported', 'needs_input', 'error'],
    );
  });

  it('exposes the same busy and lock rules the component used to compute by hand', () => {
    expect(STATES.filter((n) => selectors.busy(at(n)))).toEqual(['generating', 'saving']);
    expect(STATES.filter((n) => selectors.composerLocked(at(n)))).toEqual(['saving', 'escalated']);
    expect(STATES.filter((n) => selectors.followUp(at(n)))).toEqual(['needs_input']);
  });
});
