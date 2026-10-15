# Saved Queue and Execution Queue Architecture

Status: design only. This document does not authorize or implement a booking worker, scheduler, reservation submission, or payment.

## Goal

Separate a user's editable reservation preferences from any future work that can call the official booking service. Support many users, several credentials per user, and many target dates and opening times without sharing state across users or credentials.

The saved queue is durable user intent. An execution queue is a separately authorized, immutable request to attempt a particular saved revision at a particular time. Saving intent must never arm or run it implicitly.

## Current implementation

- `PlanService` stores manual queues as `manual_queue_draft` snapshots in the existing booking plan/revision tables. The current queue identity is scoped by user, credential ID, and target date.
- A queue revision stores ordered semantic candidates. Two-hour candidates precede one-hour candidates. The API uses optimistic `base_version` checks and stores no Token, payment password, availability snapshot, upstream node ID, or execution parameter.
- The current DTO reports `execution_state=not_started`; `can_query_upstream`, `can_book`, `can_pay`, and `can_create_job` are false. There is no modern booking job table, worker, scheduler, reservation submitter, or payment flow.
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

This layer remains usable without any executor. It is where the Vue manual grid and Agent may save human-reviewed intent in the future.

## Layer B: execution requests and worker queue

Do not turn a saved queue row into a job by status mutation. Add separate records only after the upstream booking contract, venue mapping, and approval policy have been verified.

### Proposed records

`booking_jobs` (one explicit user authorization for one credential, target date, pinned saved revision, and requested run time):

- `job_id`, `user_id`, `credential_id`
- `queue_id`, `queue_revision_id`, `queue_version_snapshot`
- `credential_version_snapshot`, `token_revision_id_snapshot`, `payment_password_revision_snapshot`
- `target_date`, `business_timezone_name`, `scheduled_at_utc_ms`, `window_policy_version`
- `state`, `state_version`, `idempotency_key`, `created_at_utc_ms`, `updated_at_utc_ms`
- current lease owner/epoch/expiry, if claimed by a worker

`booking_job_attempts` records each attempt and stage with safe outcome codes and times. It must not contain raw Token/password, authorization headers, raw upstream bodies, or unsanitized exception text.

`booking_job_candidate_outcomes` records the pinned candidate index, normalized choice, decision (`eligible`, `skipped`, `submitted`, `confirmed`, `uncertain`), and a bounded reason code. It must not reinterpret or mutate the original queue revision.

Add tenant-bound foreign keys and compound uniqueness for every owner-scoped relation. The authenticated API always filters by `user_id`; every credential reference must be revalidated as owned by that user on create and worker claim.

### Creation and idempotency

Creating a job must be an explicit authenticated action with CSRF protection and a server-generated or client idempotency key. The server pins the exact current queue revision and credential/token/password revisions in one transaction. A repeated request with the same owner and idempotency key returns the same job. It must not silently follow later edits to a queue or credential.

If a user edits a queue after scheduling, the job keeps its pinned revision. The UI must make that visible and offer an explicit cancel-and-create-again path. If the selected credential or payment-password revision changes before execution, fail closed into `needs_attention`; do not switch to a different Token or password.

### Worker and concurrency

Use a durable database claim with a lease and monotonically increasing fencing epoch. A worker first claims due work in a short transaction, releases the transaction before network I/O, then conditionally commits results only if its lease epoch and all pinned revisions still match. A stale worker cannot overwrite a newer attempt.

Enforce limits at three scopes:

- per user: bounded active jobs and predictable fairness;
- per credential/upstream account: serialize non-idempotent reservation submissions;
- global upstream endpoint: request spacing, concurrency cap, deadlines, and provider backoff.

The scheduler should order eligible jobs by `scheduled_at_utc_ms`, then creation time and job ID for deterministic ties. It must not use client clocks as authority. UTC execution time is derived from the versioned business-time policy and stored with the original timezone and target date for audit.

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

The worker may decrypt the Token only around an approved request callback. The payment password may be decrypted only in a later, separately authorized payment stage after an authoritative unpaid order has been identified. It must never be sent to an LLM, stored in job/attempt snapshots, logged, returned to the browser, or copied into a booking request before the payment contract is verified.

Do not infer unattended payment consent from adding a password. Payment needs a separate explicit product decision and authorization, plus amount/order verification and idempotency/reconciliation behavior.

## Proposed rollout and acceptance

1. **Design and evidence:** verify official reservation, order lookup, payment request, venue mapping, opening-time policy, and supported cancellation/idempotency behavior. Do not use a live account to probe write/payment calls.
2. **Persistence/API:** add job/attempt schemas, ownership constraints, idempotent job creation, queue revision pinning, cancel semantics, and read-only job history. Test two users, multiple credentials per user, several dates per credential, stale queue versions, and secret rotation races.
3. **Dry-run executor:** claim jobs, validate pinned revisions and opening windows, produce candidate decisions without sending reservation requests. Add lease/fencing, crash recovery, cancellation races, rate limits, and unknown-state tests.
4. **Reservation adapter:** only after reviewed protocol evidence and an explicit authorization boundary, add a narrowly scoped reservation request; require authoritative reconciliation and keep payment disabled.
5. **Payment:** separate design and approval. Implement only after order identity, amount, payment-password wire format, retry semantics, and user authorization are proven.

No execution layer is implemented in this branch. The present UI and APIs continue to save and read intent only.
