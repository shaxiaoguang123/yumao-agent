export function metricsFixture(scope = 'personal') {
  const trend = Array.from({ length: 7 }, (_, index) => ({ date: `2026-10-${16 + index}`, total: index === 6 ? 3 : 0, succeeded: index === 6 ? 1 : 0, failed: index === 6 ? 1 : 0, needs_attention: 0, other: index === 6 ? 1 : 0 }));
  const data = {
    scope, generated_at_utc_ms: Date.UTC(2026, 9, 22, 8), timezone: 'Asia/Shanghai', business_date: '2026-10-22',
    credentials: { total: 2, enabled: 1 },
    queues: { upcoming: 2, candidates: 6, before_opening: 1, one_hour: 2, two_hour: 4 },
    execution: { runs: 3, pending: 1, states: { ready: 1, calibrated: 0, running: 0, succeeded: 1, failed: 1, needs_attention: 0, stale: 0, empty: 0 }, trend },
  };
  if (scope === 'system') {
    data.users = { total: 3, active: 3 };
    data.diagnostics = {
      available: true, levels: { info: 12, warning: 2, error: 1 }, modules: [{ module: 'agent', count: 2 }, { module: 'upstream', count: 1 }],
      request_count: 10, failed_requests: 1, mean_request_ms: 123,
      trend: trend.map(row => ({ date: row.date, error: row.total ? 1 : 0, warning: row.total ? 2 : 0 })),
      collection: collectionFixture(), retained_from_utc_ms: Date.UTC(2026, 9, 22, 7),
    };
  }
  return data;
}
export function collectionFixture() {
  return { enabled: true, state: 'ready', role: 'web', queue_depth: 0, dropped_events: 0, failed_events: 0, retention_days: 14, last_write_at_utc_ms: Date.UTC(2026, 9, 22, 8) };
}
export function logFixture(id = 5) {
  return { event_id: id, at_utc_ms: Date.UTC(2026, 9, 22, 8, 0, id), level: 'error', module: 'agent', action: 'agent.model_call', code: 'provider_timeout',
    request_id: 'a'.repeat(32), user_id: 'synthetic-user', credential_id: 'synthetic-credential', conversation_id: 'synthetic-conversation', run_id: null, elapsed_ms: 45000,
    details: { outcome: 'failed', attempt: 2, exception_type: 'TimeoutError', frames: [{ file: 'backend/ai/provider.py', function: '_exchange', line: 190 }] } };
}
export function logsFixture() {
  return { events: [logFixture()], next_cursor: null, collection: collectionFixture(), collectors: [], queried_at_utc_ms: Date.UTC(2026, 9, 22, 8, 1), window: { since: Date.UTC(2026, 9, 21, 8, 1), until: Date.UTC(2026, 9, 22, 8, 1) } };
}
