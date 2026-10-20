# Saved Queue and Execution Queue Architecture

Status: implementation exists, but live execution is not enabled or verified. `backend/execution/` contains the per-credential scheduler, candidate reconciliation, reservation/payment protocol, and order verification. `BOOKING_EXECUTION_ENABLED` defaults to false; the worker is a separately launched process. Automated execution tests use synthetic upstream replies, and live account checks are limited to read-only validation and availability. This document remains the safety and acceptance checklist for any live execution rollout.

## User-confirmed schedule contract

The schedule is fixed to the third calendar day counting today as day one: on business date `D`, only target date `D+2` is processed. For example, Monday at 00:30 handles Wednesday's queues; the 11th handles the 13th. This supersedes the older draft's dynamically resolved `official_open` schedule for this workflow. Use the configured booking business timezone (`Asia/Shanghai` for the current deployment), not the browser or host's local timezone.

For each business date:

1. By default at 00:30 (with the reconciliation time configurable per credential within the 00:00–07:30 preparation window), inspect only the saved queue for `D+2` under each owner and credential. If that exact queue is absent or empty, create no candidate snapshot or execution work for that owner/credential/date. Do not substitute another date, credential, or Token.
2. Build an immutable candidate-execution snapshot from that queue revision and that credential's real `bookingByTime` response. Offer all court columns returned for the current credential/date; resolve each saved court preference only against that same response's court list, and skip unknown or ambiguous names rather than guessing. Do not populate availability or court choices from synthetic data. Keep the saved queue unchanged and record which candidates were removed and why.
3. Use the raw response conflict markers to remove booked cells and the blocked activity/unbookable categories described in the evidence note. Do not interpret the entire pre-opening gray grid as permanently unavailable: the official client initially paints the whole grid as `course7` outside its booking-time window, then overlays cells from `conflictList`.
4. Before the execution window, calibrate against Beijing time (the proposed default is 1 second before 07:30). At 07:30 plus that credential's configured millisecond offset, obtain fresh state and assemble the final reservation request from the current response. The 00:30 snapshot is only candidate pruning; it is never the final request payload or proof that a slot remains open.
5. Store per-credential controls for the 00:30 reconciliation time, clock-calibration lead time, post-07:30 start offset, and measured/configured delay for each verified stage (availability read, price lookup, order creation, and payment). Record query start/end times for each stage. If clock calibration or a required fresh response fails, do not run using stale state.

If a queue is edited after its 00:30 snapshot, the execution work must pin and display the exact queue revision it will use; applying a later edit requires rebuilding the snapshot. If the credential or Token revision changes, stop and require a fresh preflight rather than silently switching credentials. Agent-generated proposals are not part of this schedule; this version covers the manually saved two-hour and one-hour queues.

The reviewed `req/1.js` frontend bundle confirms display/selection rules, not a running scheduler or successful reservation contract. Its release association and physical court-to-venue mapping remain unverified. The reviewed legacy Python flow contains no CAPTCHA/sliding-challenge call; do not add a separate challenge request. If the reservation service returns a challenge or rejects the request, stop safely for user attention rather than bypassing that control.

## Proposed end-to-end flow for review

The existing frontend stays as-is. It continues to save the user's separate two-hour priority and one-hour fallback queues. A saved, non-empty queue for the exact `D+2` date is the scheduled intent; saving it makes no upstream call immediately.

### 00:30 candidate reconciliation

For every enabled credential, the scheduler reads only that owner's queue for `D+2`. It pins the queue revision and Token revision, then calls `bookingByTime` using that credential's real Token. The candidate grid uses every court in that response; each saved court name is resolved only against that same response. No queue means no request and no job.

For each candidate, map its one-hour or two-hour interval onto the response rows. A two-hour choice must cover two consecutive rows. Remove candidates that intersect a booked marker or an activity/unbookable marker from `conflictList`, and save the outcome in a separate execution snapshot without changing the user's queue. The client-side whole-grid `course7` fill before `bookingstarttime` is a display gate; it must not be mistaken for explicit `course7` entries in the raw conflict list. A 00:30 survivor is only a candidate for later checking.

### 07:30 execution

At the configured calibration lead time (initial proposal: 1 second before 07:30), compare the server clock with its trusted Beijing-time source. If time cannot be trusted, hold that credential's work. At 07:30 plus the credential's start offset, process two-hour candidates in saved order, then one-hour candidates in saved order.

At the start of that credential's execution session, load account context with `getUserInfo`/`getChildren`. Before each candidate attempt, fetch fresh `bookingByTime` state and rebuild the candidate fields from that response. If the current booking window is closed, a conflict marker now blocks any row, the court name no longer resolves uniquely, or the Token/queue revision changed, skip or hold the candidate; never send a payload built from the 00:30 response. For an eligible candidate, continue with `getPayPrice`, `createBookingBytime`, `openPlatformPayOrder`, and order verification through `payOrderForPhone`/`payOrderDetails`. Do not silently fall back to a default reservation person if account-context lookup fails.

The legacy flow makes a fresh `bookingByTime` call for each candidate and permits up to three rounds. For the scheduled worker, the safer initial proposal is one ordered pass, with a fresh availability read before each candidate; retry only a stage whose outcome is known to be safe. If order creation or payment may have succeeded but its response is uncertain, reconcile the order before trying another candidate. Stop the credential's queue after authoritative success.

Clock calibration, reconciliation time, post-07:30 offset, and each stage's configured delay are stored per credential. Record request start/end and elapsed time for every upstream stage. The worker processes each owner/credential independently, serializes order writes for one credential, and applies shared upstream rate limits across users. A failure for one credential must not switch to another credential's Token or queue.

This flow currently interprets the requested payment stage as automatic payment of the matching order using that credential's encrypted payment-password revision. The quoted `getPayPrice` amount must be tied to the same candidate and order, and payment is complete only after authoritative order verification. Price ceiling and the exact retry policy are review items before implementation.

## Goal

Separate a user's editable reservation preferences from any future work that can call the official booking service. Support many users, several credentials per user, and many target dates and opening times without sharing state across users or credentials.

The saved queue is durable user intent. A non-empty manual queue for the exact `D+2` target date is the user's authorization to attempt those candidates at the scheduled window. At 00:30, the scheduler derives a separate immutable execution job from that queue revision; saving or editing a queue never makes an immediate upstream call, and a Token by itself never arms a job.

## Current implementation

- `PlanService` stores manual queues as `manual_queue_draft` snapshots in the existing booking plan/revision tables. The current queue identity is scoped by user, credential ID, and target date.
- A queue revision stores ordered semantic candidates. Two-hour candidates precede one-hour candidates. The API uses optimistic `base_version` checks and stores no Token, payment password, availability snapshot, upstream node ID, or execution parameter.
- The current DTO reports `execution_state=not_started`; `can_query_upstream`, `can_book`, `can_pay`, and `can_create_job` are false. There is no modern booking job table, worker, recurring D+2 scheduler, reservation submitter, or payment flow.
- An audit of all 46 existing local and `origin/*` tracking refs on 2026-10-15 found no recurring scheduler or worker implementation. Legacy `POST /api/run` invokes `run_plan` only in response to a request; its `autoRun` flag only enables an optional delay between attempts in that invocation. The `threading.Timer` found in the AI provider only aborts one timed-out network request. No `git fetch` was performed, so this audit covers the refs already present locally.
- Live availability is a separate read-only surface. Its observations are time-limited display data and are not an execution authorization or a booking inventory snapshot.
- Credentials are per-user records with versioned Token revisions and account-continuity checks. The payment password is being added as a separate encrypted current secret with its own revision; it is not used by current queries or queue saving.

## Layer A: saved intent queues

Keep the present API/service responsibility narrow:

```text
SavedQueue = (owner_user_id, credential_id, target_date, current_revision_id, version)
QueueRevision = immutable ordered candidate snapshot + context + created_at
Candidate = court display preference + start/end + duration
```

Rules:

1. `owner_user_id` is derived from the authenticated session, never accepted from a client payload.
2. `credential_id` is an opaque reference owned by that user. It identifies which upstream account the intent belongs to; the Token itself never enters queue JSON.
3. `target_date` is interpreted in the configured booking business timezone and is part of the queue identity. Different dates and credentials never overwrite each other.
4. Reads and writes return only the selected credential scope. Legacy unbound queues remain visibly unbound history; do not silently attach them to whichever credential is currently selected.
5. Writes append a revision with compare-and-swap. A lost response is reconciled by reading the current version; it must not create a second queue.
6. Deleting/clearing a queue affects the current projection while immutable revisions remain available for history and audit.
7. Queue editing and queue listing never call availability, booking, order, or payment APIs.

This layer remains usable without any executor. The Vue manual grid saves user-reviewed intent. Agent proposals are out of scope for the D+2 scheduler until separately requested.

## Layer B: execution requests and worker queue

Do not turn a saved queue row into a job by status mutation. Add separate records only after the request contract, per-response court resolution, and approval policy have been verified. A synthetic or global static court catalog is not needed for the runtime grid: use all real courts returned for that credential and target date, and resolve saved preferences only within that response. Never carry upstream court identifiers across credentials, dates, or responses. The physical venue label can remain unverified until a source proves one.

### Proposed records

`booking_jobs` (one scheduler-created execution for one owner, credential, exact `D+2` target date, pinned saved revision, and resolved run time):

- `job_id`, `user_id`, `credential_id`
- `queue_id`, `queue_revision_id`, `queue_version_snapshot`
- `credential_version_snapshot`, `token_revision_id_snapshot`, `payment_password_revision_snapshot`
- `target_date`, `business_timezone_name`, `scheduled_at_utc_ms`, `window_policy_version`
- `state`, `state_version`, `idempotency_key`, `created_at_utc_ms`, `updated_at_utc_ms`
- current lease owner/epoch/expiry, if claimed by a worker

`booking_job_attempts` records each attempt and stage with safe outcome codes and times. It must not contain raw Token/password, authorization headers, raw upstream bodies, or unsanitized exception text.

`booking_job_candidate_outcomes` records the pinned candidate index, normalized choice, decision (`eligible`, `skipped`, `submitted`, `confirmed`, `uncertain`), and a bounded reason code. It must not reinterpret or mutate the original queue revision.

Add an immutable preflight observation/snapshot relation keyed by job, queue revision, Token revision, and target date. It records the raw-response fingerprint, observed time window, candidate outcomes, and stage timings, but not the raw response or any secret. The 07:30 final read creates a separate final-resolution record; it must not overwrite the 00:30 observation.

Add tenant-bound foreign keys and compound uniqueness for every owner-scoped relation. The authenticated API always filters by `user_id`; every credential reference must be revalidated as owned by that user on create and worker claim.

### Creation and idempotency

At 00:30, the scheduler creates a job only after an authenticated-owner/credential-scoped lookup finds a non-empty queue for the exact `D+2` date and an enabled, usable credential. In one transaction it pins the queue and Token revisions and derives a stable idempotency key from the owner, credential, target date, queue revision, and schedule-policy version. Reprocessing the same input returns the same job. It must not silently follow later edits to a queue or credential.

If a user edits a queue after the 00:30 snapshot, the job keeps its pinned revision. The UI must make that visible and offer an explicit cancel-and-rebuild path. A queue added after the snapshot needs a deliberate preflight rerun before 07:30 or it is skipped for that opening; the next daily D+2 pass targets a different date. If the selected credential or Token revision changes before execution, fail closed into `needs_attention`; do not switch to a different Token. Payment-password revision changes block the payment stage.

### Worker and concurrency

Use a durable database claim with a lease and monotonically increasing fencing epoch. A worker first claims due work in a short transaction, releases the transaction before network I/O, then conditionally commits results only if its lease epoch and all pinned revisions still match. A stale worker cannot overwrite a newer attempt.

Enforce limits at three scopes:

- per user: bounded active jobs and predictable fairness;
- per credential/upstream account: serialize non-idempotent reservation submissions;
- global upstream endpoint: request spacing, concurrency cap, deadlines, and provider backoff.

The scheduler should generate work only for the current business date's `D+2` queues, then order eligible per-credential work by configured start offset, creation time, and job ID for deterministic ties. It must not use client clocks as authority. Store the configured local event times, offsets, timezone, target date, and their resolved UTC instants for audit. No work is generated for other target dates during that daily pass.

### State machine

Initial proposed states:

```text
scheduled -> preflight -> waiting_for_window -> submitting -> reconciling
                                             -> succeeded
                                             -> failed
                                             -> submission_uncertain
                                             -> needs_attention
scheduled/preflight -> cancel_requested -> canceled
```

`submission_uncertain` is essential. If a reservation request may have reached the upstream service but the response is lost, do not blindly resubmit. Reconcile through an authoritative order/booking lookup first. Only use automatic retry when the upstream endpoint has a verified idempotency contract.

“Succeeded” requires authoritative confirmation, not merely an HTTP 2xx response. Availability `unknown` or a stale observation can never be treated as an available slot. A verified mapping from displayed court name to upstream venue/court identifier must exist before an execution candidate can be submitted.

## Booking and payment boundary

Token and payment password are distinct secrets. Store each encrypted with purpose-specific authenticated context and independent revisions. Public credential DTOs expose only presence/revision metadata. The execution job pins those revisions but never copies secret values.

The worker may decrypt the Token only around an approved request callback. For the requested payment stage, it may decrypt only the password revision paired with the same credential, after an authoritative unpaid order has been identified. Neither secret may be sent to an LLM, stored in job/attempt snapshots, logged, returned to the browser, or copied into unrelated requests. The payment adapter must bind the quoted amount to the created order, enforce the reviewed price ceiling, and reconcile uncertain results before retrying.

## Proposed rollout and acceptance

1. **Design and evidence:** verify official reservation, order lookup, payment request, venue mapping, opening-time policy, and supported cancellation/idempotency behavior. Do not use a live account to probe write/payment calls.
2. **Persistence/API:** add job/attempt schemas, ownership constraints, idempotent job creation, queue revision pinning, cancel semantics, and read-only job history. Test two users, multiple credentials per user, several dates per credential, stale queue versions, and secret rotation races.
3. **Dry-run executor:** claim jobs, validate pinned revisions and opening windows, produce candidate decisions without sending reservation requests. Add lease/fencing, crash recovery, cancellation races, rate limits, and unknown-state tests.
4. **Reservation adapter:** only after reviewed protocol evidence and the saved-queue authorization boundary are clear, add a narrowly scoped reservation request; require authoritative reconciliation and keep payment disabled until its amount and retry gates are implemented.
5. **Payment:** implement the requested stage only after order identity, amount, payment-password wire format, per-credential price ceiling, and retry/reconciliation behavior are proven.

The execution layer is implemented separately from saved queue revisions. It pins a queue revision, creates a candidate snapshot, refreshes availability before execution, and records run stages. The runtime must keep booking execution disabled until the request/response contract, physical venue mapping, order reconciliation, and payment behavior have been accepted. No real reservation or payment was performed during the current Agent verification.
