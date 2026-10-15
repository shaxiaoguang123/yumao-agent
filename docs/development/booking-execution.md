# Scheduled booking execution

## User and queue boundaries

- A saved manual queue is the editable intent. It is scoped by application user, Token credential, and reservation date.
- The only automatically processed date is the current business date plus two days. On the 15th, the worker considers only the 17th queue.
- A non-empty queue is the user's authorization to attempt the reservation and pay. A missing or empty queue creates no execution run.
- At the per-Token reconciliation time (default 00:30), the worker re-resolves the saved official booking category and reads that Token's real `bookingByTime` response. Explicit `conflictList` entries and rows hidden by `timeList.status` are removed. The pre-opening global client time gate is not treated as an unavailable-court signal.
- The remaining candidate list is stored as an immutable execution snapshot. It contains category and court display names plus the selected interval; it does not reuse court IDs from the earlier response.
- Before execution, the worker calibrates against the upstream HTTPS `Date` header. After 07:30 plus the per-Token offset, it refreshes `bookingByTime` for every candidate and builds coordinates, quote, and order payloads from that same fresh response.
- Candidates run in saved order, with two-hour candidates before one-hour candidates, for up to three rounds. The first confirmed paid order ends the run.
- An uncertain order-creation response or unverified payment result moves the run to `needs_attention`. It does not issue another order or payment request because the upstream flow has no proven idempotency key.
- The worker does not call a slider/CAPTCHA endpoint. If an upstream step rejects or requires a challenge, the run records a safe error code and stops or continues only where the result is known to be a read-only/definite rejection.

## Per-Token controls

The credential page stores these settings independently for each Token:

- reconciliation time, constrained to before 07:30;
- time calibration lead, default 1,000 ms before opening;
- start offset after 07:30;
- added delays before category, availability, user, children, quote, order, payment, and payment-verification steps.

Settings are copied into the execution snapshot when the queue is reconciled. Changing them afterward affects a later snapshot.

## Starting the worker

The Flask web process does not start booking execution. Run one dedicated worker under a process supervisor after the deployment is ready:

```sh
python -m backend.migrate
python -m backend.execution.worker
```

Enable it with `BOOKING_EXECUTION_ENABLED=true` and configure the server-side official request cipher plus a positive `UPSTREAM_GET_USER_INFO_MIN_INTERVAL_MS`. The setting defaults to `false`; the worker refuses to start when it is disabled. Do not start multiple worker processes against the same database.

## Verification boundary

Unit and integration tests use local SQLite databases and fake transports. They do not contact the upstream service, create reservations, or send payments. The first live run still depends on the deployment's clock source, AES configuration, Token validity, and the upstream response contract remaining compatible.
