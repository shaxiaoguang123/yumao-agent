# V1 Reservation Intent and Plan Management Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **Plan status:** V1 Reservation Intent and Plan Management / In Execution — Task 0 PARTIAL; Task 1A complete; Task 1B BLOCKED.

**Goal:** Add user-owned manual booking plans with immutable semantic `ReservationIntent` revisions, optimistic locking, and a Vue editor, while keeping all upstream execution outside this phase.

**Architecture:** Extend the current Flask/Vue/SQLite identity and Credential foundation with a user-scoped `BookingPlan`, append-only `PlanRevision`, strict intent validation, and one `PlanService` used by both the manual API and any later Planning Agent. Add a pure business-time booking-window policy for date display; this phase does not query availability or create jobs.

**Tech Stack:** Python 3.12, Flask, `sqlite3`, existing project dependencies, Vue 3, Vite, Vitest, and Conda `test`.

**Spec:** [V1 Final Architecture Spec](../specs/2026-10-07-multiuser-booking-design.md), especially sections 3, 6, 9, 10, 13, and 14.

## Verified Baseline (2026-10-09)

- Task 1A work started from `feature/03-reservation-intent` at `160cfa9f78f8c31b6937e845c4bb1b0528f6ef92`, with `origin/main` at `2ca7d2b3ba83fa218dc0924433e05c25e7a8e87b` already in its history. Preserve this branch and its plan/evidence history. The remote feature branch remains behind and is not part of this task.
- The codebase has no ReservationIntent booking-window policy or BookingPlan/PlanRevision implementation. The existing `backend/time_utils.py` remains legacy code and is not the source for the configured business-time policy.
- Task 0 remains **PARTIAL** in `docs/superpowers/evidence/2026-10-08-booking-plan-catalog.md`. Its venue/query-scope, venue/court, and booking-type gaps continue to block Task 1B; no production catalog or semantic option is confirmed.
- Source schema is version 4. The checked-in migration manifest is:

  | Version | File | SHA-256 |
  | --- | --- | --- |
  | 1 | `0001_identity.sql` | `767fa35441ed2ddd0260980d9abfdbcddbcc1f2a7983a6103461d2fde1b0aa04` |
  | 2 | `0002_credentials.sql` | `a036a6b4915eb5ea2f9e8c0a196fb57e7287a9a3566814d20e6d934344f9b465` |
  | 3 | `0003_upstream_gate_started_at.sql` | `e77af261bbb1bd322aaeb9477d3447fada7e51d3d4db83de49b98ba7948252c1` |
  | 4 | `0004_credential_audit_binding_state.sql` | `9618ec410d4a67a3b3ef1bea1ff6d3e60e1689d0215478440083c1c4f38ab8f1` |

- The configured application database file is absent, so there is no persistent application `schema_migrations` history to claim as applied. The isolated temporary preview database contains versions 1–4 with checksums matching the current source manifest; it is not the application's configured database.
- Before applying migrations, Task 2 must re-read the branch's `CURRENT_SCHEMA_VERSION`, migration filenames/checksums, configured database's `schema_migrations`, and required structure read-only. An empty DB may use the full ordered chain; a valid older v1–v3 prefix may advance one version at a time to v4; `0005_booking_plans.sql` runs only after v4 is verified. Unknown versions, gaps, checksum mismatches, or structural anomalies stop without repairing or overwriting data.

## Scope of This Plan

This is the manual-plan foundation slice of the semantic planning stage. It implements creating, viewing, editing, and reviewing immutable plan revisions. The data model and `PlanService` are the shared persistence boundary that a later Planning Agent must use.

Planning Agent, LLM Provider settings, live AvailabilityService queries, BookingJob, Worker, preparation queues, booking, payment, and Tailscale are explicitly deferred to separate reviewed plans. The editor must not imply that a saved intent is available or scheduled for execution.

## Git and Worktree Boundary

- Work only in `/Users/sha/Document/worktree-codex/reservation-intent-plan/yumao-agent` on `feature/03-reservation-intent`; do not develop on `main`.
- This existing worktree already contains `origin/main` through its prior normal merge. Preserve all local commits. Preserve the primary checkout's `.env`, uncommitted local-run note, unrelated untracked files, and running preview servers.
- Every implementation Task ends in a separate commit. Stage only the exact files listed by that Task; never use `git add .`, `git clean`, reset, or broad staging.
- Keep the already-merged Admin Invitation UI changes as part of the current `origin/main` base; do not repeat that iteration or alter its branch history here.
- Never commit `.env`, `req/`, database/WAL files, preview artifacts, Tokens, real personal data, or generated frontend assets. Read `req/` only for Task 0, in memory, from the primary checkout; do not copy captures into the worktree.
- No real upstream requests are permitted. All tests use temporary databases and synthetic catalog values.
- Before starting this plan, verify this worktree is clean and that `origin/main` is an ancestor. If uncommitted changes appear, stop and preserve them; do not reset or clean. Run the existing baseline only when the base changes:

  `conda run -n test python -m unittest discover -s backend/tests -v`

  `cd frontend && npm ci && npm test -- --run && npm run build`

  The backend suite includes current v4 schema-readiness/migration tests on temporary databases. Do not expect ReservationIntent tests or schema v5 to exist yet, and do not migrate the configured application database.

## Global Constraints

- Preserve Flask + Vue + SQLite and the existing server-side Session, CSRF, and SQL-level `user_id` isolation.
- BookingPlan describes only the user's semantic intent. A PlanRevision stores an immutable canonical snapshot and hash; it never stores availability, a historical court `nodeid`, array indexes, `coordinatesList`, or a historical price.
- Target date is interpreted in the configured IANA `BOOKING_TIMEZONE`, default `Asia/Shanghai`; browser and host time zones do not determine booking windows.
- The only dates queryable by the current window policy are the business-local dates `D`, `D+1`, and `D+2`. A saved future ReservationIntent never makes a date queryable. `query_open_at` is calculated from target date `T-2` at 00:00 in the business time zone. The observed 07:30 value is display-only; it is not a confirmed open time.
- This phase cannot query the upstream system. Its `BookingWindowPolicy` always reports `can_book=false` and `can_pay=false`; it does not accept a client-supplied confirmed opening time. A future confirmed opening can only come from a validated server-side upstream observation in a later phase.
- In Task 1A, `can_query` means only that the pure configured-timezone calendar predicate is satisfied. It is not authorization to send a network request and cannot initiate any upstream call.
- Venue scope, venue/court labels, semantic keys, and booking type come only from the evidence-gated, versioned Task 0 catalog. The catalog is a user-selection aid, never evidence of a target date's current `nodeList` or availability. A `booktype` value is not a duration.
- Each immutable PlanRevision snapshots its interpretation context: `BOOKING_TIMEZONE`, nullable deployment currency code/exponent, catalog version, venue query scope, and semantic display-label snapshots. Configuration/catalog changes never rewrite an existing revision. Historical price ceilings always display in their saved currency/exponent; no conversion is implicit. A later Job must fail closed when its currency context is incompatible until an explicit new revision/confirmation or migration. Existing revisions and edits preserve saved context; new plans use active configuration. V1 has no in-place context migration.
- Reject unknown intent fields, including Credential, Job, payment, Token, availability, price quote, upstream court/time identifiers, indexes, or coordinates.
- No Agent or LLM code is added in this slice. Later Agent changes must be reviewed by the user and persisted by the same `PlanService`, with no direct SQL write path.
- Do not change the Credential implementation, read `.env` in tests, contact the upstream service, or use old Python booking code as protocol evidence.

## Review Focus

- Client-supplied or stale venue/court identifiers must never be persisted as trusted execution facts; test that intent input accepts catalog keys only and the server resolves the query scope.
- A stale plan version must not overwrite a newer revision; test concurrent/stale `base_version` updates and exact 409 behavior.
- Cross-user plan IDs must be indistinguishable from missing plans; verify SQL queries bind the authenticated `user_id`.
- Time-window eligibility must be limited to current business-local dates D through D+2; test a saved distant date, a date outside the current three-day window, and the exact T-2 00:00 edge.
- Boolean values must not pass as integer duration, priority, or price fields; use strict JSON-type checks and test `true` and `false` explicitly.
- A later change to business timezone, currency/exponent, or catalog must not change any existing revision's interpretation; test snapshots across a changed active configuration.
- A saved plan must not look like a booking task or current availability; test that the API/UI expose intent and window information only, with no execution/job state.

## Current Execution Gate

- Task 0 is still **PARTIAL**; its evidence document is not to be marked complete by the Task 1A implementation.
- Task 1A is complete and remains independent of VenueCatalog.
- Task 1B remains **BLOCKED** until a new evidence review confirms a visible venue option and its query-scope mapping, venue ownership of court labels, and a supported semantic booking-type mapping. Do not add real venue/type values, production catalog entries, or catalog fixtures before that gate is met.
- Task 2 through Task 6 retain their existing sequence and do not become authorized merely because Task 1A passes. They remain gated on Task 1B because PlanRevision/API/UI contracts snapshot and expose a catalog version and venue-scoped semantic options.

---

## File Layout

- `backend/settings.py`: validated `BOOKING_TIMEZONE` and deployment-owned booking currency metadata (Task 1A).
- `backend/booking_window.py`: pure business-time query-window calculation; no network or database access (Task 1A).
- `backend/plans/catalog.py`: server-side venue and semantic choice catalog, deferred to Task 1B and blocked until Task 0 evidence is sufficient.
- `backend/plans/models.py`, `validation.py`, `service.py`: immutable intent/revision types, strict normalization, and user-scoped transactional PlanService.
- `backend/migrations/0005_booking_plans.sql`, `backend/db.py`: schema version 5, booking-plan tables, readiness contract, and migration checksum enforcement.
- `backend/api/plans.py`, `backend/api/booking_window.py`, `backend/app.py`: authenticated user-scoped plan and read-only booking-window routes.
- `backend/tests/test_settings.py` and `backend/tests/test_booking_window.py`: settings and pure policy coverage (Task 1A); `backend/tests/test_plan_catalog.py` belongs to Task 1B and is not created or populated with real values while that task is blocked.
- `backend/tests/test_plan_validation.py`, `test_plan_service.py`, `test_plans_api.py`, and `test_db.py`: future pure boundary, temporary-DB, ownership, migration, and API tests.
- `frontend/src/api/plans.js` and `plans.test.js`: plan/window HTTP helpers.
- `frontend/src/views/PlansView.vue` and `PlansView.test.js`: plan list, create/edit form, revision history, and version-conflict UX.
- `frontend/src/router.js`, `App.vue`, and `HomeView.vue`: authenticated plan navigation.

## Task 0: Evidence-Gated Venue Catalog

**Files:**

- Read only: local `req/` captures and `req/1.js` in the primary checkout.
- Create: `docs/superpowers/evidence/2026-10-08-booking-plan-catalog.md`.
- No production code or real request is allowed in this Task.

**Interfaces:**

- Evidence covers all of: top-level `venue_query_nodeid` versus each `nodeList[].nodeid`; observed venue labels; `nodeList[].sitename` court names and how the official frontend presents/selects them; the semantic keys the V1 catalog can safely expose; and the independently observed booking-type fields.
- Compare `appointmentType` and `booktype` evidence separately. Do not infer duration from either field (in particular, `booktype=2` does not mean two hours). Record only booking types with direct request and official-frontend support; if no semantic mapping is evidenced, block that option rather than guess.
- The versioned catalog records provenance, source files, observation date/sample scope, supported venue/type/court options, and applicability limits. It is a user-selection aid only; it does not claim that a venue/court exists in a future target-date `nodeList` or is available.
- The evidence note records relationships and evidence limits, not real query-scope identifiers. Exact query identifiers are kept only in the server-side catalog source and never in fixtures. Never record Token, identity/profile values, full payloads, user dates, prices, orders, or raw capture text.
- If evidence cannot establish a venue mapping, court semantic option, or booking-type mapping, stop the affected catalog option and report the missing evidence; do not substitute `DEFAULT_NODEID` from legacy Python code or invent a value.
- Each PlanRevision snapshots `catalog_version` and the selected venue/court/type semantic label snapshots. A catalog update cannot silently rename, remap, or reinterpret an existing revision.
- Task 0 is a read-only evidence audit, so it has no product failing/passing test. It remains PARTIAL. Task 1A may test only timezone/currency settings and pure calendar policy; catalog tests belong to Task 1B and stay blocked until its evidence gate is met.

- [ ] **Step 1: Inspect the local official source and matched captures in memory**

  Confirm the top-level venue query-scope field, court-level identifier field, venue/court labels and selection path, and booking-type versus duration semantics. Use only local captures/official frontend source from the primary checkout; make no live request.

- [ ] **Step 2: Write the sanitized catalog evidence**

  Add provenance, catalog version, source files, observed semantic choices, supported type mappings, applicability scope, and unresolved limits. Keep real upstream identifiers in the server catalog source only. Verify the note contains no capture body, real identifier, or personal/secret value.

- [ ] **Step 3: Commit the evidence**

  Stage only `docs/superpowers/evidence/2026-10-08-booking-plan-catalog.md` and commit as `docs: record booking plan catalog evidence`.

## Task 1A: Business-Time Policy and Independent Settings

**Status:** COMPLETE. Task 1A is independent of Task 0 catalog evidence; this does not unblock Task 1B.

**Files:**

- Modify: `backend/settings.py`.
- Create: `backend/booking_window.py`.
- Modify: `backend/tests/test_settings.py`.
- Create: `backend/tests/test_booking_window.py`.

**Interfaces:**

- `load_settings(env) -> AppSettings` adds `booking_timezone_name`, default `Asia/Shanghai`. Require a non-empty valid IANA key accepted by `zoneinfo.ZoneInfo`; invalid or non-canonical whitespace values fail fast. Tests pass an explicit synthetic environment and never read `.env`.
- `BOOKING_CURRENCY_CODE` and `BOOKING_CURRENCY_MINOR_UNIT_EXPONENT` remain deployment-owned and independent of VenueCatalog. They are an optional all-or-none pair: code is exactly three uppercase ASCII letters; exponent is an integer from 0 through 4 inclusive. If both are absent, settings contain `None` for both. Do not infer currency from upstream samples or expose a user-selected currency.
- `BookingWindowPolicy` receives the validated active `BOOKING_TIMEZONE`; no host-local or browser timezone participates. `business_date_at_utc(now_utc_ms) -> date` converts a UTC epoch-millisecond instant into the active zone. `queryable_target_dates(now_utc_ms) -> tuple[date, date, date]` returns exactly D, D+1, D+2 by local calendar arithmetic.
- `describe(target_date, now_utc_ms, intent_timezone_snapshot=None) -> BookingWindowState` is pure and performs no I/O. It includes the active timezone, business date, default target date D+2, target date, current D/D+1/D+2 window, `query_open_at_utc_ms`, estimated display-only T-2 07:30 local time, `can_query`, `can_book`, `can_pay`, `contract_status`, and `reason_code`.
- `can_query` means only that the calendar window and T-2 time boundary are satisfied; it is not network permission or an upstream validation result. `can_book` and `can_pay` are always `false`, `resolved_official_open_at_utc_ms` is always absent, and no confirmed-open time can be supplied by a caller.
- Compute T-2 00:00 from a local calendar date in the active IANA zone, then convert that instant to UTC milliseconds. Never subtract fixed 48-hour durations or consult the host timezone. For an ambiguous local midnight, use its first occurrence; for a midnight gap, use the first valid instant on that same local date. If the whole local date is skipped, fail closed with no query-open instant and a reason code.
- Represent the estimated T-2 07:30 as a local display value with the active timezone and an explicit unconfirmed/display-only state; do not present it as a UTC-confirmed opening. `can_query` is based on T-2 00:00, not 07:30.
- If `intent_timezone_snapshot` differs from the active operational timezone, return `can_query=false` with a timezone-context-mismatch reason. Do not reinterpret the historical intent date/time under the new configuration. Historical display remains tied to the saved snapshot; a future query requires a new confirmed plan context or an explicit migration outside this phase.
- A distant target date remains a valid intent input to later PlanService work, but this pure policy reports it outside D..D+2 and non-queryable. Task 1A does not create or save plans.

**Tests:**

- Default timezone, valid IANA zones, invalid/empty timezone rejection, and explicit-env behavior independent of process `.env`.
- Currency pair absent, both present, either half missing, invalid code shapes, exponent bounds 0 and 4, and rejected out-of-range/non-integer exponent values.
- Business-date conversion from UTC under the configured timezone, exact D/D+1/D+2 set, far-future target non-queryability, and instants immediately before/at/after T-2 00:00.
- Month/year rollover, leap day, and DST spring/fall transitions. Include ambiguous/nonexistent local-midnight behavior and fail-closed behavior for a skipped local civil date.
- Active timezone mismatch blocks `can_query`; the estimated 07:30 remains display-only and unconfirmed; all returned states have `can_book=false` and `can_pay=false`.
- No test reads `.env`, `req/`, or a real database. Use synthetic settings and fixed UTC epoch milliseconds.

- [x] **Step 1: Write failing Task 1A tests**

  Add only the settings and pure policy cases above. Do not create `test_plan_catalog.py` in this task.

- [x] **Step 2: Run focused tests and verify expected failures**

  Run: `conda run -n test python -m unittest discover -s backend/tests -p 'test_settings.py' -v` and `conda run -n test python -m unittest discover -s backend/tests -p 'test_booking_window.py' -v`.

  Expected: missing timezone/currency settings and missing `backend.booking_window` interface fail for the intended reasons.

- [x] **Step 3: Implement the minimum settings and pure policy**

  Modify only `backend/settings.py` and create `backend/booking_window.py`. Do not add routes, catalog files, database changes, or network clients.

- [x] **Step 4: Run focused, full backend, frontend, and build verification**

  Run the focused discovery commands above, then `conda run -n test python -m unittest discover -s backend/tests -v`, `cd frontend && npm test -- --run`, and `cd frontend && npm run build`.

- [x] **Step 5: Commit Task 1A**

  Stage exactly `backend/settings.py`, `backend/booking_window.py`, `backend/tests/test_settings.py`, `backend/tests/test_booking_window.py`, and this plan document for the Task 1A execution record. Commit as `feat: add independent booking window policy`.

## Task 1B: Evidence-Gated VenueCatalog

**Status: BLOCKED — Task 0 remains PARTIAL. Do not start this task until its evidence gate is explicitly re-reviewed.**

**Files when unblocked:**

- Create: `backend/plans/__init__.py`, `backend/plans/catalog.py`, `backend/tests/test_plan_catalog.py`.
- Modify the evidence document only after new reliable local evidence is found.

**Unblock requirements:**

- Confirm a visible venue choice and its relationship to the `bookingByTime` parent query scope without publishing identifier values in evidence/fixtures.
- Confirm which court labels belong to each confirmed venue and that each key resolves uniquely under a catalog version.
- Confirm the supported semantic booking type from official source and matching local request evidence; keep duration independent from `appointmentType` and `booktype`.
- Record provenance, client/version scope, evidence limitations, and public-repository visibility considerations before creating any runtime catalog entry.

**Interfaces and future tests when unblocked:**

- Preserve the two-level options API: venue options first; after `venue_key`, only that venue/version's semantic court options and supported booking types. Never return upstream IDs, coordinates, response order, or availability.
- Test same labels in different venues, duplicate labels/keys within one venue, wrong-venue keys, catalog-version retention, and DTO exclusion of all upstream identifiers.
- Populate real server-side mappings only from the re-reviewed evidence. Do not invent values, use `DEFAULT_NODEID`, or add synthetic production options to unblock tests.

Task 2 through Task 6 remain in their existing order but cannot begin solely because Task 1A passes. They depend on Task 1B's catalog version and semantic option contract.

## Task 2: Plan Schema and Migration

**Files:**

- Modify: `backend/db.py`.
- Create: `backend/migrations/0005_booking_plans.sql`.
- Test: `backend/tests/test_db.py`.

**Interfaces:**

- `CURRENT_SCHEMA_VERSION` becomes 5; `check_schema_ready` requires the version-5 booking-plan tables and verifies migration checksums, foreign keys, and required columns. The explicit migration runner remains the only migration path.
- A truly new empty database is initialized by the existing runner through every migration in order: 0001, 0002, 0003, 0004, then 0005. A verified v4 database receives only 0005. A valid older v1–v3 database advances one contiguous version at a time; the runner must never skip a version.
- Before any upgrade, verify the applied version/filename/checksum history and the actual required structure. Unknown versions, gaps, checksum mismatches, missing/incompatible structures, or foreign-key violations stop migration without overwriting data or attempting automatic repair. Existing migration files 0001–0004 remain immutable.
- `booking_plans` stores `plan_id`, `user_id`, `current_revision_id TEXT NOT NULL`, `version INTEGER NOT NULL CHECK(version > 0)`, and UTC created/updated timestamps. It has `UNIQUE(plan_id, user_id)` for the revision-to-plan foreign key and a deferred composite foreign key `(current_revision_id, plan_id, user_id) REFERENCES booking_plan_revisions(revision_id, plan_id, user_id) DEFERRABLE INITIALLY DEFERRED`; it has no Credential, Job, availability, or payment fields.
- `booking_plan_revisions` stores `revision_id` as its primary key, `plan_id`, `user_id`, `revision_number INTEGER NOT NULL CHECK(revision_number > 0)`, canonical `intent_json`, SHA-256 `intent_sha256`, `created_by_user_id`, and `created_at_utc_ms`. It has `UNIQUE(revision_id, plan_id, user_id)` exactly matching the plan pointer's referenced parent columns, `UNIQUE(plan_id, user_id, revision_number)`, and a foreign key `(plan_id, user_id) REFERENCES booking_plans(plan_id, user_id)`.
- Canonical `intent_json` includes the server-resolved `venue_query_nodeid` and a server-owned interpretation snapshot: `BOOKING_TIMEZONE`, nullable currency code and minor-unit exponent, catalog version, and selected venue/court/booking-type display-label snapshots. Hash the intent and interpretation snapshot together. The query ID stays server-side and is never returned in user DTOs. Never update an old snapshot when deployment settings or catalog entries change.
- Revisions are append-only. The migration adds database guards against revision update/delete; the mutable plan row may only advance its current-revision pointer and version through PlanService. Creating the plan and its first revision must satisfy the deferred pointer constraint before commit.

- [ ] **Step 1: Recheck migration base and write failing migration/readiness tests**

  Re-read the checked-in manifest and any configured database history read-only. Test full fresh initialization through 0001–0005; sequential continuation from valid v1, v2, and v3 prefixes; and v4-to-v5 upgrade. For existing DBs, test unknown version, version gap, checksum mismatch, and incompatible schema fail without changing rows/schema. Test exact required columns, NOT NULL/CHECK/parent uniqueness constraints, and actual inserts: a valid plan plus first revision in one transaction succeeds at COMMIT; NULL current revision, zero/negative plan version or revision number, cross-plan, cross-user, invalid current revision ID, and mismatched composite reference fail. A failed deferred-FK commit must roll back both plan/revision rows. Also test revision update/delete rejection, immutable interpretation-snapshot storage, and preservation of existing users and Credential rows. Do not assume 0005 is next if the re-read base is not verified v4.

- [ ] **Step 2: Run focused database tests**

  Run: `conda run -n test python -m unittest backend.tests.test_db -v`

  Expected: version-5 readiness and table assertions fail before the migration exists.

- [ ] **Step 3: Add migration 0005 and readiness requirements**

  Add only 0005 to the existing explicit migration runner sequence. Preserve 0001–0004; do not use `executescript`, semicolon splitting, automatic repair, or destructive replacement. Keep `BEGIN IMMEDIATE`/rollback behavior controlled by the existing runner.

- [ ] **Step 4: Run focused database tests**

  Run: `conda run -n test python -m unittest backend.tests.test_db -v`

  Expected: migration, checksum, foreign-key, immutability, and preservation assertions pass.

- [ ] **Step 5: Commit Task 2**

  Stage exactly `backend/db.py`, `backend/migrations/0005_booking_plans.sql`, and `backend/tests/test_db.py`. Commit as `feat: add booking plan revision schema`.

## Task 3: ReservationIntent Validation and PlanService

**Files:**

- Create: `backend/plans/models.py`, `backend/plans/validation.py`, `backend/plans/service.py`.
- Test: `backend/tests/test_plan_validation.py`, `backend/tests/test_plan_service.py`.

**Interfaces:**

- `parse_reservation_intent(payload: Mapping[str, object], *, today_business_date: date, catalog: VenueCatalog, interpretation_context: PlanInterpretationContext) -> ReservationIntent` rejects unknown keys and returns a normalized immutable value. The context is selected by the server and never accepted from the request.
- API JSON bodies are capped at 16 KiB before parsing. Unknown keys fail with 400; client-supplied node IDs, array indexes, `coordinatesList`, availability, real prices/quotes, Credential, Job, payment, Token, and execution fields are always rejected.
- The accepted intent fields are `target_date`, `venue_key`, `preferred_start_times`, `duration_minutes`, semantic `booking_type`, ordered `court_preferences`, `fallback_policy`, and nullable `price_ceiling_minor`. The server resolves `venue_key` and semantic option keys using the selected catalog version and freezes the venue query scope plus display-label snapshots into the revision.
- `venue_key`, `booking_type`, and each court `semantic_key` must be non-empty strings matching the selected catalog scope. Each client court-preference object contains only `semantic_key` and `priority`; labels and the upstream venue query scope are supplied and snapshotted by the server, never trusted from the request.
- `preferred_start_times` is a required array of 1–8 exact 24-hour `HH:MM` strings; order is the user's explicit priority order and duplicate times are rejected. `duration_minutes` must have exact JSON type integer (never bool), be 30–240 inclusive, and be a multiple of 30. These are bounded semantic-input limits only; they do not assert that the upstream offers every duration, which a later resolver must verify.
- `court_preferences` has at most 16 entries. Each semantic key is unique and must resolve exactly once within both the selected `venue_key` and `catalog_version`; a key from another venue is rejected even if its display label matches. Duplicate court labels/semantic keys within the same venue/version are ambiguous and rejected. `priority` must have exact JSON type integer (never bool), be unique, and form contiguous values 1..N; the canonical array is sorted by priority. It may be empty only when `allow_any_court_in_venue=true`; otherwise at least one explicit court preference is required.
- `fallback_policy` accepts exactly two boolean fields and `allowed_start_time_range`. Booleans require exact JSON boolean type. If `allow_time_shift=false`, the range must be null. If true, the range is required with inclusive `start`/`end` exact `HH:MM`, start not after end, and it must contain every explicit preferred time. The shift baseline is always `preferred_start_times[0]`; duration never changes.
- `price_ceiling_minor` is null or exact JSON integer (never bool/float), from 0 through `Number.MAX_SAFE_INTEGER`, and is accepted only when the deployment currency/exponent pair exists. The browser accepts a decimal string, converts with digit-string/BigInt arithmetic, checks the safe-integer limit, and only then sends the integer; it never multiplies a floating-point value to derive minor units.
- `target_date` must be a real ISO date and not before the current business-local date. Plan creation is allowed for any later date; query eligibility remains independently limited to current D through D+2.
- Canonical JSON uses UTF-8, sorted keys, compact separators, and no floats; its SHA-256 covers both ReservationIntent and the interpretation snapshot.
- `PlanService.create_plan(user_id, payload, now_utc_ms) -> PlanDTO`, `list_plans(user_id) -> tuple[PlanDTO, ...]`, `get_plan(user_id, plan_id) -> PlanDTO`, `list_revisions(user_id, plan_id) -> tuple[PlanRevisionDTO, ...]`, and `update_plan(user_id, plan_id, base_version, payload, now_utc_ms) -> PlanDTO` are the only plan write/read interfaces. The service derives `today_business_date` from the injected clock and `BookingWindowPolicy`.
- Create and update use short `BEGIN IMMEDIATE` transactions. Every lookup binds `user_id`. On create, allocate plan and first revision IDs before insertion, insert the plan with its current-revision pointer, insert the first revision, then commit so the deferred composite FK is checked against both rows. For updates, the transaction first reads the owned plan and compares `base_version`; stale versions return 409 even if the submitted content would normalize to the current intent. Only after the version matches may identical normalized content return a no-op without a new revision. Otherwise append a revision and advance the pointer/version atomically.
- Editing an existing plan preserves its stored timezone/currency/catalog interpretation snapshot. Current query eligibility always uses active operational `BOOKING_TIMEZONE`; if it differs from the plan snapshot, the server returns a derived context-mismatch reason and `can_query=false`. The UI preserves the historical local date/time display and requires the user to create a new plan under current settings (or wait for a separately approved explicit migration). New plans use current configuration.

- [ ] **Step 1: Write failing strict-schema and service tests**

  Cover exact type checks including booleans in every integer field; 16 KiB body limit; preferred-time count/order/duplicates; duration limits and increments; court count/key/priority/empty-list combinations including cross-venue and duplicate-label rejection; fallback field/type/range/baseline combinations; exact minor-unit ceiling and currency/exponent availability; unknown sensitive fields; stable context/hash snapshots across config/catalog changes; same-plan current-pointer consistency; stale base_version with identical content returning 409; transaction version check before no-op; atomic revision append; rollback; and cross-user not-found behavior.

- [ ] **Step 2: Run the focused tests**

  Run: `conda run -n test python -m unittest backend.tests.test_plan_validation backend.tests.test_plan_service -v`

  Expected: plan model/service imports or assertions fail.

- [ ] **Step 3: Implement immutable intent parsing and PlanService**

  Keep every database query user-scoped. Never perform availability or upstream calls inside PlanService.

- [ ] **Step 4: Run the focused tests**

  Run the same command as Step 2. Expected: all validation, versioning, ownership, and rollback tests pass.

- [ ] **Step 5: Commit Task 3**

  Stage exactly `backend/plans/models.py`, `backend/plans/validation.py`, `backend/plans/service.py`, `backend/tests/test_plan_validation.py`, and `backend/tests/test_plan_service.py`. Commit as `feat: add reservation intent plan service`.

## Task 4: Authenticated Plan and Booking-Window APIs

**Files:**

- Modify: `backend/app.py`.
- Create: `backend/api/plans.py`, `backend/api/booking_window.py`.
- Test: `backend/tests/test_plans_api.py`, `backend/tests/test_app_factory.py`.

**Interfaces:**

- Register `GET/POST /api/plans`, `GET/PATCH /api/plans/<plan_id>`, and `GET /api/plans/<plan_id>/revisions`.
- The same `GET /api/plans/options?catalog_version=<optional>&venue_key=<optional>` endpoint has two explicit response modes and echoes the resolved `catalog_version`. Without `venue_key`, it returns the semantic venue list for the active version (default) or a requested retained version. With `venue_key`, it returns only that venue's semantic court options and supported semantic `booking_type` values in the selected version. Unknown venue/version pairs fail safely. Both modes omit upstream node IDs, coordinates, and availability.
- Register `GET /api/booking-window?target_date=YYYY-MM-DD`; it calls only BookingWindowPolicy and never contacts upstream. It always calculates query eligibility from active operational configuration, reports only current D..D+2, shows 07:30 as estimated, always returns `can_book=false` and `can_pay=false`, and accepts no confirmed-open value from the client. Plan DTOs preserve historical date/time/currency labels from revision snapshots and return a context-mismatch reason with `can_query=false` if the saved timezone differs from active operational timezone.
- All plan endpoints require a valid application Session; POST/PATCH require CSRF and strict JSON field allowlists. PATCH requires positive `base_version` with exact JSON integer type; bool is rejected.
- Cross-user and missing IDs both return non-disclosing 404. Invalid intent returns 400; stale version returns 409; unauthenticated and CSRF behavior reuses existing application contracts.
- DTOs return semantic fields, server-side version/revision IDs, the immutable interpretation context (business timezone, currency/exponent, catalog version, and label snapshots), query-window information, and any derived context-mismatch reason. They never return a Token, account fingerprint, venue query node ID, availability, price quote, array index, or coordinate.

- [ ] **Step 1: Write failing route and isolation tests**

  Test unauthenticated 401, mutation CSRF 403, create/list/get/update/revision history, stale 409, unknown fields 400, missing/cross-user identical 404, two-level options behavior (venue list first, then venue-scoped court/type options), rejected wrong-venue keys, retained catalog-version lookup, no upstream identifiers/coordinates/availability, exact active D..D+2 eligibility, saved-timezone mismatch blocking query eligibility, historical labels/timezone preserved in the DTO, false booking/payment flags, no client-settable confirmed-open field, and absence of any upstream transport call.

- [ ] **Step 2: Run focused API tests**

  Run: `conda run -n test python -m unittest backend.tests.test_plans_api backend.tests.test_app_factory -v`

  Expected: plan and booking-window routes are not registered.

- [ ] **Step 3: Implement blueprints and app registration**

  Reuse existing Session/CSRF helpers and current-user context; pass `user_id` explicitly into PlanService.

- [ ] **Step 4: Run focused API tests**

  Run the same command as Step 2. Expected: endpoint, isolation, and status-code assertions pass.

- [ ] **Step 5: Commit Task 4**

  Stage exactly `backend/app.py`, `backend/api/plans.py`, `backend/api/booking_window.py`, `backend/tests/test_plans_api.py`, and `backend/tests/test_app_factory.py`. Commit as `feat: add user-scoped plan APIs`.

## Task 5: Manual Plan Editor

**Files:**

- Modify: `frontend/src/router.js`, `frontend/src/App.vue`, `frontend/src/views/HomeView.vue`.
- Modify: `frontend/src/router.test.js`.
- Create: `frontend/src/api/plans.js`, `frontend/src/api/plans.test.js`, `frontend/src/views/PlansView.vue`, `frontend/src/views/PlansView.test.js`.

**Interfaces:**

- The authenticated `/plans` route supports create, edit, and immutable revision history using the plan API.
- Load semantic venue options first using `GET /api/plans/options` without `venue_key`. After the user selects one, load that venue's court options and supported booking_type using the same endpoint with `venue_key` and the resolved catalog version. Do not retain or expose upstream venue/court node IDs.
- Form fields map only to ReservationIntent and follow the exact list/count/type/range constraints above. Court preferences and booking type must come from the selected venue/version response; duration remains a separate control. Court fallback is limited to the selected venue; time fallback uses the explicit first preferred time as its baseline.
- Price entry is a decimal text field converted to minor units with digit-string/BigInt arithmetic; never compute minor units by multiplying a JavaScript float. Show the revision's snapshotted currency/exponent and timezone, not a changed active configuration.
- Show the server booking-window response. A target outside active-operational D..D+2 is saved as intent but clearly marked non-queryable; saving it does not initiate availability. If the saved timezone differs from active operational timezone, preserve the historical date/time display, show the mismatch, and direct the user to create a new plan under the current context before future querying/execution. Show historical price ceilings with their snapshotted currency/exponent. All plans are intent-only and not availability-verified. Never show a real-open or payment-ready state, stale prices, or coordinates. Do not add a Job/execute button or Agent chat in this slice.
- Save sends the current `base_version`. A 409 keeps the user's draft, offers a reload of the latest revision, and never silently overwrites it.

- [ ] **Step 1: Write failing API-helper, view, and route tests**

  Test credentials-included requests, CSRF on mutations, two-step venue then venue-scoped option loading, semantic-only payloads, no node IDs/coordinates, every max-count/type boundary, add/reorder/remove court preferences, rejecting a court/type from another venue, same-venue fallback and time baseline/range validation, exact decimal-to-minor conversion without floating-point multiplication, context snapshot display after active config changes, timezone mismatch warning and non-queryability under active operational timezone, distant-target non-queryability, immutable revision history, version conflict draft retention, and auth/window guard behavior.

- [ ] **Step 2: Run focused frontend tests**

  Run: `cd frontend && npm test -- --run src/api/plans.test.js src/views/PlansView.test.js src/router.test.js`

  Expected: missing plan API/view/route fails after the existing Vitest infrastructure starts normally.

- [ ] **Step 3: Implement the plan API helper and Vue editor**

  Keep all time-window facts server-supplied. The browser may format display values but must not derive T-2, official opening, or availability.

- [ ] **Step 4: Run focused frontend tests and production build**

  Run: `cd frontend && npm test -- --run src/api/plans.test.js src/views/PlansView.test.js src/router.test.js`

  Then run: `cd frontend && npm run build`

  Expected: focused tests pass and Vite produces a successful production build.

- [ ] **Step 4a: Run real-browser interaction and visual acceptance**

  After the editor exists, run the actual Vue application in Chrome/Chromium or a working Playwright browser against mocked APIs or an isolated temporary Flask service. Use synthetic users, catalog options, plans, revisions, and errors; never read real `.env`, `req/`, or application databases. Intercept and record every unexpected external request. Reuse existing browser tooling or a repository-external temporary tool environment; do not add project dependencies or CI changes merely to claim browser coverage.

  Check desktop **1440 × 900**, tablet **768 × 1024**, phone **390 × 844**, and narrow phone **320 × 700**. Generate screenshots with the real browser and inspect every captured image. At each viewport, check navigation, alignment, typography, spacing, clipping/overlap, horizontal overflow, clickable/touch controls, keyboard Tab order, and visible focus. Inspect browser console errors, uncaught exceptions, and failed/unexpected network activity; distinguish deliberately simulated API failures from unexpected failures.

  Exercise login and route permissions; plan creation, editing, and immutable revision history; venue-first and venue-scoped court/type loading; preferred times, independent duration, and court priority add/reorder/remove controls; loading, empty, save-success, validation-error, and request-error states. A `base_version` 409 must preserve the draft, explain the conflict, and offer an explicit latest-version refresh without silently replacing unsaved input. Verify a distant target is visibly non-queryable, saved/active timezone and currency-context mismatches are explained without reinterpreting the revision, and estimated 07:30 is labelled as an estimate rather than a confirmed opening. Confirm there is no booking execution or payment action.

  Record **PASS / FAIL / BLOCKED / NOT_APPLICABLE** for each check, with page, viewport, scenario, and screenshot/trace paths. Keep raw screenshots, traces, recordings, and reports outside the public repository; mask synthetic secret-like fields in screenshots and never capture real credentials. A missing browser environment is BLOCKED, not replaced by jsdom output, static HTML, generated pictures, or a successful build. Vitest/jsdom, production build, real-browser interactions, and screenshot review are separate evidence. Resolve or explicitly report browser findings before claiming Task 5 acceptance. This requirement applies only after Task 5 is implemented: Task 1A adds no frontend page, and the current baseline cannot certify the future `/plans` editor.

- [ ] **Step 5: Commit Task 5**

  Stage exactly `frontend/src/api/plans.js`, `frontend/src/api/plans.test.js`, `frontend/src/views/PlansView.vue`, `frontend/src/views/PlansView.test.js`, `frontend/src/router.js`, `frontend/src/App.vue`, `frontend/src/views/HomeView.vue`, and `frontend/src/router.test.js`. Commit as `feat: add manual reservation plan editor`.

## Task 6: Full Acceptance and Git Integration

**Files:**

- Modify only Task-owned files if acceptance reveals a defect; keep each fix in its owning Task commit where practical.
- Plan checkbox/status updates are optional. If tracked updates are made, save them in an exact-path documentation-only commit separate from all Task code commits; alternatively track execution in a separate record and leave this plan unchanged. Do not leave plan edits uncommitted before integration.

**Interfaces:**

- Schema version 5 startup remains read-only; migrations run only through the explicit migration command.
- Before applying migrations, recheck the current branch manifest, configured database history, and required structure. A new empty database uses the full ordered chain; a valid older prefix advances sequentially, with 0005 applied only after verified v4. Unknown versions, gaps, checksum mismatches, or structure anomalies stop without repairs or data changes.
- All tests use temporary SQLite databases and synthetic catalog/intent values. No test reads `.env` or `req/`, and no real upstream request is made.
- No BookingJob, AvailabilityService query, Agent, LLM Provider, booking, payment, or Tailscale behavior appears in the result.

- [ ] **Step 1: Review full diff and exact Task commit contents**

  Confirm every Task commit includes its listed source, tests, and required config. Confirm `.env`, `req/`, databases/WAL, logs, temp preview artifacts, and generated frontend output are absent.

- [ ] **Step 2: Run full offline acceptance**

  Run: `conda run -n test python -m unittest discover -s backend/tests -v`

  Run: `cd frontend && npm ci && npm test -- --run && npm run build`

  Also run `git diff --check main...HEAD`, `git status --short`, version-5 migration/checksum readiness tests, and a test-source audit confirming no external upstream call. Do not rely on bare `git diff --check`, which misses committed branch changes when the worktree is clean.

  Repeat the Task 5 real-browser contract in a clean, isolated local acceptance worktree after the feature exists. Cover the implemented `/plans` editor and the existing `/login`, `/register`, `/`, `/credentials`, `/account`, and `/admin/invitations` pages at all four specified viewports. Recheck unauthenticated/user/admin routing, mutation feedback and duplicate-submit protection, Credential confirmation/cancellation, one-time invitation display/copy/cleanup and uncertain-result acknowledgement, plus every plan scenario listed in Step 4a. Use only synthetic data and mocked APIs or temporary Flask databases, with unexpected external traffic blocked. Inspect all screenshots as well as console/JavaScript/network evidence and record per-check statuses and defect severity/reproduction paths outside the repository. If mocked APIs are used, do not claim they independently verify backend authorization; retain the backend isolation/Session/CSRF tests as separate evidence. Component tests and build output do not satisfy this browser gate. Record any missing environment/scenario as BLOCKED and any unresolved visual/interaction defect explicitly; do not mark Task 6 complete merely because automated unit tests passed.

- [ ] **Step 3: Synchronize with local main**

  Task 6 runs only after Tasks 0–5 implement the feature. Recheck the latest `main`; if it advanced since the last clean rebase, verify this worktree is clean, rebase `feature/03-reservation-intent` onto it, resolve conflicts without destructive reset, and rerun the complete backend/frontend tests, production build, schema v5 migration/checksum tests, `git diff --check main...HEAD`, and `git status --short`. Do not merge while the primary `main` checkout has conflicting tracked changes; preserve its local-run edit and untracked files.

  After synchronization changes application files, repeat the real-browser acceptance against that final candidate; screenshots from an earlier SHA do not certify the integrated result.

- [ ] **Step 4: Record acceptance without a feature commit**

  Task 6 is integration/acceptance-only and produces no feature commit. If a durable acceptance record is required, make it a separate documentation-only commit with an exact file list; do not create an empty commit or include unrelated files.

- [ ] **Step 5: Obtain explicit integration approval**

  After Task 6 passes, present the diff and wait for the user's explicit approval before merging or tagging. Only then may the primary checkout run `git merge --ff-only feature/03-reservation-intent`, verify `main`, create `v1-reservation-intent`, and remove this worktree/branch. No merge or tag occurs before that approval.

## Follow-On Plan Boundaries

The next separately reviewed plan may add the Planning Agent and complete OpenAI-compatible Provider configuration on top of the same PlanService. Live availability and the UpstreamContractAdapter, Credential booking profile, BookingJob/Worker, preparation queues, createBooking, payment, and Tailscale remain later stages. No direct Agent writes, CAPTCHA bypass, or upstream rate-limit evasion is allowed.
