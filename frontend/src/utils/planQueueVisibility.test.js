import { describe, expect, it } from 'vitest';
import { visibleIntentPlans, visibleManualQueuePlans } from './planQueueVisibility.js';

const queue = (date, candidates = [{}]) => ({
  plan_id: `queue-${date}`,
  target_date: date,
  candidates,
});

describe('plan date retention and ordering', () => {
  it('keeps yesterday and later while sorting manual queues from nearest to farthest', () => {
    const visible = visibleManualQueuePlans([
      queue('2026-10-14'), queue('2026-10-12'), queue('2026-10-15'), queue('2026-10-13'),
    ], { businessDate: '2026-10-15' });

    expect(visible.map(item => item.target_date)).toEqual(['2026-10-14', '2026-10-15']);
  });

  it('does not reveal retained-away dates when a date filter is set', () => {
    expect(visibleManualQueuePlans([queue('2026-10-08')], {
      businessDate: '2026-10-10', dateFilter: '2026-10-08',
    })).toEqual([]);
  });

  it('sorts Agent intents chronologically and applies the same retention cutoff', () => {
    const intent = date => ({ plan_id: date, intent: { target_date: date } });
    const visible = visibleIntentPlans([
      intent('2026-10-12'), intent('2026-10-09'), intent('2026-10-08'), intent('2026-10-10'),
    ], { businessDate: '2026-10-10' });

    expect(visible.map(item => item.intent.target_date)).toEqual(['2026-10-09', '2026-10-10', '2026-10-12']);
  });
});
