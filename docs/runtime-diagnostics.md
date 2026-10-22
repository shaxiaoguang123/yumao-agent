# Runtime diagnostics and activity metrics

## Access and scope

- `/admin/logs` and `/api/admin/logs` require a current administrator Session. A normal user receives HTTP 403 from the API. An anonymous or revoked Session receives 401.
- `/api/metrics/overview` aggregates the authenticated user's data. A supplied `user_id` never selects another account.
- `/api/admin/metrics` aggregates all accounts and is administrator-only.
- Diagnostics responses use `Cache-Control: no-store`. Each application response includes a server-generated `X-Request-ID`; HTTP errors expose this identifier to the frontend without changing their existing status/code or Session handling.

## What is recorded

API endpoints, methods, status codes and duration; credential operation outcomes; upstream endpoint aliases and status codes; model call duration, retry and validation codes; queue conversation phase and counts; scheduler failures; execution snapshot counts and stages; administrator actions and log reads.

Events link to internal user/credential IDs and, when present, request, conversation and execution-run IDs. They include process role, PID and a release SHA when `APP_RELEASE` or the release directory identifies a 7–40 character hexadecimal SHA. Local worktrees otherwise show `development`.

Only explicitly allowed scalar metadata is stored. Token values, payment passwords, API keys, Session/CSRF cookies, prompts, messages, raw request/response bodies, configured provider URLs, exception messages and local variables are excluded. Safe exception frames contain only repository-relative filenames (external frames use `<dependency>`), functions and line numbers. The legacy file-log endpoints stay disabled.

An execution detail also reads a bounded projection of the existing durable execution-stage table. It never exports the execution snapshot, order payload or credential material. Related diagnostic events are limited to the latest 100; durable stages to the latest 500, with explicit truncation flags.

## Storage and operation

Collection is enabled by default. `RUNTIME_LOGS_ENABLED=false` disables it; business metrics continue to work. Tests disable background collectors by default unless they explicitly enable this setting.

The log DB is a sibling of the business DB: `yumao.sqlite3` produces `yumao.diagnostics.sqlite3`. No business schema migration is required. The new file is private (0600), and the existing systemd services already allow writes in `/var/lib/yumao-agent`. The collector does not require journal access, sudo or a new service.

Each process has one bounded queue (2,048 events) and a daemon writer, which writes batches to the separate SQLite DB. This DB uses SQLite's default rollback journal; collection does not change business DB pragmas or join business transactions. The DB has a 200 MiB page budget. Hourly maintenance retains at most 14 days / 50,000 events; free pages are reused. Physical DB space is not reclaimed by an automatic VACUUM. SQLite rollback journals and ordinary filesystem overhead can temporarily require additional free space.

Queue saturation drops events and increments a counter. Write failures drop that batch, mark collection degraded, and emit a fixed safe stderr notification. Collection failures never authorize a retry, change business outcomes or block the request/booking path on disk I/O. Shutdown waits up to two seconds; forced exits can lose the final queued events. This is diagnostic telemetry, not a replacement for the durable execution and credential audit tables.

Collector heartbeats indicate collection health, not scheduler success. A heartbeat older than 120 seconds is marked stale. The page reports queued/dropped/failed events and last collection times. Counts describe retained data; events discarded or predating collection cannot be reconstructed. API health checks and successful diagnostic polling are excluded from ordinary request totals; administrator log reads are still audited separately.

The backend must be running to view logs in the application. Startup failures before collector initialization and a completely unavailable Web process still require the host's systemd journal.

## Metric definitions

- **Future queues / candidates:** current, nondeleted, nonempty manual queue revisions whose target date is today or later in the configured booking timezone. Old revisions and expired targets are excluded. These counts do not claim credential readiness or an actual reservation.
- **Before opening:** queues above whose target-minus-two-days 07:30 opening has not arrived. Exactly 07:30 is no longer eligible. This is time eligibility only.
- **One/two-hour candidates:** independent groups in saved semantic queues; never inferred from orders or combined into booked hours.
- **Seven-day execution chart:** current state of durable runs created during the current business day and previous six days. Success is the executor's confirmed success state. `empty`, `stale`, ready, calibrated and running appear as other states, not failures.
- **Request volume/latency:** recorded ordinary API request-completion events in the last 24 hours. Mean latency is not P95. Only HTTP 5xx completions count as failed requests.
- **Error chart / module distribution:** warning/error diagnostic events, not unique failing requests. One request can generate multiple events. Missing collection is shown as unavailable, never converted to healthy zeroes.

## Verification

Backend tests cover authorization, revoked roles, account isolation, current revisions, 07:30 eligibility, cursor pagination, secret exclusion, safe error frames, upstream billing categories, durable stage projections, retention, queue saturation and concurrent collector roles.

Frontend tests cover scope gating, loading/error/retry states, late-response suppression, filter/pagination behavior, safe detail rendering and request IDs. Browser scenarios check personal/system metrics and log filtering/details/unavailability at the existing viewport matrix. Browser fixtures are synthetic; they do not prove real model or upstream service capability and never create or pay for an order.
