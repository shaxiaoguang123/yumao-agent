# V1 Reservation Intent and Plan Management Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **Plan status:** V1 Reservation Intent and Plan Management / Ready for Review

**Goal:** Add user-owned manual booking plans with immutable semantic `ReservationIntent` revisions, optimistic locking, and a Vue editor, while keeping all upstream execution outside this phase.

**Architecture:** Extend the current Flask/Vue/SQLite identity and Credential foundation with a user-scoped `BookingPlan`, append-only `PlanRevision`, strict intent validation, and one `PlanService` used by both the manual API and any later Planning Agent. Add a pure business-time booking-window policy for date display; this phase does not query availability or create jobs.

**Tech Stack:** Python 3.12, Flask, `sqlite3`, existing project dependencies, Vue 3, Vite, Vitest, and Conda `test`.

**Spec:** [V1 Final Architecture Spec](../specs/2026-10-07-multiuser-booking-design.md), especially sections 3, 6, 9, 10, 13, and 14.

## Verified Baseline (2026-10-08)

- The implementation base is `main` at `bd12ac8` / `v1-credential-token-lifecycle`. The plan branch is `feature/03-reservation-intent` at `869a743`; it contains this plan only and must be preserved.
- The current code has no `BookingPlan`, `PlanRevision`, ReservationIntent validator, booking-window API, or plan UI.
- Source schema is version 4. The checked-in migration manifest is:

  | Version | File | SHA-256 |
  | --- | --- | --- |
  | 1 | `0001_identity.sql` | `767fa35441ed2ddd0260980d9abfdbcddbcc1f2a7983a6103461d2fde1b0aa04` |
  | 2 | `0002_credentials.sql` | `a036a6b4915eb5ea2f9e8c0a196fb57e7287a9a3566814d20e6d934344f9b465` |
  | 3 | `0003_upstream_gate_started_at.sql` | `e77af261bbb1bd322aaeb9477d3447fada7e51d3d4db83de49b98ba7948252c1` |
  | 4 | `0004_credential_audit_binding_state.sql` | `9618ec410d4a67a3b3ef1bea1ff6d3e60e1689d0215478440083c1c4f38ab8f1` |

- The configured application database file is absent, so there is no persistent application `schema_migrations` history to claim as applied. The isolated temporary preview database contains versions 1–4 with checksums matching the current source manifest; it is not the application's configured database.
- Before applying any new migration, Task 2 must re-read the branch's `CURRENT_SCHEMA_VERSION`, migration filenames/checksums, and any configured database's `schema_migrations` read-only. Only a verified version-4 base may receive `0005_booking_plans.sql`; any other version or checksum mismatch is a stop condition.

## Scope of This Plan

This is the manual-plan foundation slice of the semantic planning stage. It implements creating, viewing, editing, and reviewing immutable plan revisions. The data model and `PlanService` are the shared persistence boundary that a later Planning Agent must use.

Planning Agent, LLM Provider settings, live AvailabilityService queries, BookingJob, Worker, preparation queues, booking, payment, and Tailscale are explicitly deferred to separate reviewed plans. The editor must not imply that a saved intent is available or scheduled for execution.

## Git and Worktree Boundary

- Work only in `/Users/sha/Document/worktree-codex/reservation-intent-plan/yumao-agent` on `feature/03-reservation-intent`; do not develop on `main`.
- The feature branch starts from the reviewed `main` commit tagged `v1-credential-token-lifecycle`. Preserve the primary checkout's local `.env`, uncommitted local-run note, three unrelated untracked files, and running preview servers.
- Every implementation Task ends in a separate commit. Stage only the exact files listed by that Task; never use `git add .`, `git clean`, reset, or broad staging.
- Keep the separate `feature/admin-invitations-ui` iteration out of this branch. If that feature is later approved and merged to `main`, preserve this worktree and rebase `feature/03-reservation-intent` onto the updated `main` before implementation/integration acceptance.
- Never commit `.env`, `req/`, database/WAL files, preview artifacts, Tokens, real personal data, or generated frontend assets. Read `req/` only for Task 0, in memory, from the primary checkout; do not copy captures into the worktree.
- No real upstream requests are permitted. All tests use temporary databases and synthetic catalog values.
- After plan approval and implementation, sync with the latest local `main`; rebase if it advanced, then run all backend tests, frontend tests, production build, `git diff --check`, and migration/checksum checks. Integrate with `git merge --ff-only feature/03-reservation-intent`, then create `v1-reservation-intent` on verified `main` and remove the feature branch/worktree. No Git remote is configured.

## Global Constraints

- Preserve Flask + Vue + SQLite and the existing server-side Session, CSRF, and SQL-level `user_id` isolation.
- BookingPlan describes only the user's semantic intent. A PlanRevision stores an immutable canonical snapshot and hash; it never stores availability, a historical court `nodeid`, array indexes, `coordinatesList`, or a historical price.
- Target date is interpreted in the configured IANA `BOOKING_TIMEZONE`, default `Asia/Shanghai`; browser and host time zones do not determine booking windows.
- The only dates queryable by the current window policy are the business-local dates `D`, `D+1`, and `D+2`. A saved future ReservationIntent never makes a date queryable. `query_open_at` is calculated from target date `T-2` at 00:00 in the business time zone. The observed 07:30 value is display-only; it is not a confirmed open time.
- This phase cannot query the upstream system. Its `BookingWindowPolicy` always reports `can_book=false` and `can_pay=false`; it does not accept a client-supplied confirmed opening time. A future confirmed opening can only come from a validated server-side upstream observation in a later phase.
- Venue scope, venue/court labels, semantic keys, and booking type come only from the evidence-gated, versioned Task 0 catalog. The catalog is a user-selection aid, never evidence of a target date's current `nodeList` or availability. A `booktype` value is not a duration.
- Each immutable PlanRevision snapshots its interpretation context: `BOOKING_TIMEZONE`, nullable deployment currency code/exponent, catalog version, venue query scope, and semantic display-label snapshots. Configuration/catalog changes never rewrite an existing revision. Existing revisions and edits use their saved context; new plans use active configuration. V1 has no in-place context migration.
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

---

## File Layout

- `backend/settings.py`: validated `BOOKING_TIMEZONE` and deployment-owned booking currency metadata.
- `backend/booking_window.py`: pure business-time query-window calculation; no network or database access.
- `backend/plans/catalog.py`: server-side venue and semantic choice catalog created only from Task 0 evidence.
- `backend/plans/models.py`, `validation.py`, `service.py`: immutable intent/revision types, strict normalization, and user-scoped transactional PlanService.
- `backend/migrations/0005_booking_plans.sql`, `backend/db.py`: schema version 5, booking-plan tables, readiness contract, and migration checksum enforcement.
- `backend/api/plans.py`, `backend/api/booking_window.py`, `backend/app.py`: authenticated user-scoped plan and read-only booking-window routes.
- `backend/tests/test_booking_window.py`, `test_plan_validation.py`, `test_plan_service.py`, `test_plans_api.py`, and `test_db.py`: pure boundary, temporary-DB, ownership, migration, and API tests.
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

- [ ] **Step 1: Inspect the local official source and matched captures in memory**

  Confirm the top-level venue query-scope field, court-level identifier field, venue/court labels and selection path, and booking-type versus duration semantics. Use only local captures/official frontend source from the primary checkout; make no live request.

- [ ] **Step 2: Write the sanitized catalog evidence**

  Add provenance, catalog version, source files, observed semantic choices, supported type mappings, applicability scope, and unresolved limits. Keep real upstream identifiers in the server catalog source only. Verify the note contains no capture body, real identifier, or personal/secret value.

- [ ] **Step 3: Commit the evidence**

  Stage only `docs/superpowers/evidence/2026-10-08-booking-plan-catalog.md` and commit as `docs: record booking plan catalog evidence`.

## Task 1: Business-Time Policy and Safe Catalog

**Files:**

- Modify: `backend/settings.py`.
- Create: `backend/booking_window.py`, `backend/plans/__init__.py`, `backend/plans/catalog.py`.
- Test: `backend/tests/test_settings.py`, `backend/tests/test_booking_window.py`, `backend/tests/test_plan_catalog.py`.

**Interfaces:**

- `load_settings(env) -> AppSettings` adds `booking_timezone_name`, defaulting to `Asia/Shanghai`, and validates it with `zoneinfo.ZoneInfo`; invalid IANA zones fail fast. It also validates the optional deployment currency/exponent pair.
- Booking currency is deployment-owned, never user-selected. `BOOKING_CURRENCY_CODE` and `BOOKING_CURRENCY_MINOR_UNIT_EXPONENT` are an all-or-none pair; validate the code as three uppercase ASCII letters and the exponent as an integer from 0 through 4. If absent, plans may omit `price_ceiling_minor`, but a non-null ceiling cannot be entered.
- `BookingWindowPolicy.business_date_at_utc(now_utc_ms: int, timezone_name: str) -> date`, `queryable_target_dates(now_utc_ms: int, timezone_name: str) -> tuple[date, date, date]`, and `describe(target_date: date, now_utc_ms: int, timezone_name: str) -> BookingWindowState` use a server-selected timezone: active `BOOKING_TIMEZONE` for new plans or the saved timezone for an existing revision. The tuple is exactly that timezone's current local date D, D+1, D+2. `can_query` is true only when the target is in that tuple; saving a distant intent does not extend it. The state returns `query_open_at_utc_ms` from T-2 00:00 and display-only `estimated_open_at_utc_ms` at T-2 07:30. For this phase `can_book` and `can_pay` are always false; no confirmed-open argument is exposed. Any later validated opening observation is server-internal and outside this plan.
- `VenueCatalog.list_options(catalog_version) -> tuple[VenueOption, ...]` exposes only semantic keys and display labels to the browser. Server-side resolution uses the exact evidence-backed query scope for that catalog version. Retain older versions referenced by saved plans; never silently remap them. The catalog distinguishes semantic booking type from duration.

- [ ] **Step 1: Write failing timezone and catalog tests**

  Test default `Asia/Shanghai`, invalid timezone rejection, exact D/D+1/D+2 query set, a saved distant target remaining non-queryable, UTC instants immediately before/at/after T-2 local midnight, estimated 07:30 display-only behavior, `can_book=false`/`can_pay=false` for every input in this phase, all-or-none currency settings, valid exponent bounds, versioned catalog labels, separate booking-type/duration semantics, and that option DTOs never return query node IDs.

- [ ] **Step 2: Run the focused tests and verify expected failures**

  Run: `conda run -n test python -m unittest backend.tests.test_settings backend.tests.test_booking_window backend.tests.test_plan_catalog -v`

  Expected: missing settings/policy/catalog interfaces fail.

- [ ] **Step 3: Implement settings, pure policy, and catalog**

  Re-read only the needed local source values in memory as Task 0 requires and populate the server-side mapping from that evidence. Do not call upstream or reuse the legacy `backend/config.py` node ID.

- [ ] **Step 4: Run the focused tests**

  Run the same command as Step 2. Expected: all focused tests pass.

- [ ] **Step 5: Commit Task 1**

  Stage exactly `backend/settings.py`, `backend/booking_window.py`, `backend/plans/__init__.py`, `backend/plans/catalog.py`, `backend/tests/test_settings.py`, `backend/tests/test_booking_window.py`, and `backend/tests/test_plan_catalog.py`. Commit as `feat: add booking window policy and plan catalog`.

## Task 2: Plan Schema and Migration

**Files:**

- Modify: `backend/db.py`.
- Create: `backend/migrations/0005_booking_plans.sql`.
- Test: `backend/tests/test_db.py`.

**Interfaces:**

- `CURRENT_SCHEMA_VERSION` becomes 5; `check_schema_ready` requires the version-5 booking-plan tables and verifies the migration checksum, foreign keys, and required columns.
- `booking_plans` stores `plan_id`, `user_id`, `current_revision_id`, integer `version`, and UTC created/updated timestamps. It has a composite owner key and a deferred composite foreign key proving the current revision belongs to the same plan and user; it has no Credential, Job, availability, or payment fields.
- `booking_plan_revisions` stores `revision_id`, `plan_id`, `user_id`, one-based `revision_number`, canonical `intent_json`, SHA-256 `intent_sha256`, `created_by_user_id`, and `created_at_utc_ms`; enforce unique revision numbers per plan and composite foreign keys to the owning plan/user.
- Canonical `intent_json` includes the server-resolved `venue_query_nodeid` and a server-owned interpretation snapshot: `BOOKING_TIMEZONE`, nullable currency code and minor-unit exponent, catalog version, and selected venue/court/booking-type display-label snapshots. Hash the intent and interpretation snapshot together. The query ID stays server-side and is never returned in user DTOs. Never update an old snapshot when deployment settings or catalog entries change.
- Revisions are append-only. The migration adds database guards against revision update/delete; the mutable plan row may only advance its current-revision pointer and version through PlanService. Creating the plan and its first revision must satisfy the deferred pointer constraint before commit.

- [ ] **Step 1: Recheck migration base and write failing migration/readiness tests**

  Re-read the checked-in manifest and configured database history without writes. If a configured database exists, require its applied checksums to match. Test fresh version-5 migration from a verified v4 temporary DB, exact required columns/constraints, same-plan/user current-revision pointer enforcement, cross-user composite foreign-key rejection, revision update/delete rejection, checksum mismatch failure, immutable interpretation-snapshot storage, and preservation of existing users and Credential rows. If the observed source/database base is not v4, stop rather than assuming 0005 is next.

- [ ] **Step 2: Run focused database tests**

  Run: `conda run -n test python -m unittest backend.tests.test_db -v`

  Expected: version-5 readiness and table assertions fail before the migration exists.

- [ ] **Step 3: Add migration 0005 and readiness requirements**

  Use the existing explicit migration runner transaction; do not edit migrations 0001–0004 and do not use `executescript` or semicolon splitting.

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
- `preferred_start_times` is a required array of 1–8 exact 24-hour `HH:MM` strings; order is the user's explicit priority order and duplicate times are rejected. `duration_minutes` must have exact JSON type integer (never bool), be 30–240 inclusive, and be a multiple of 30. These are bounded semantic-input limits only; they do not assert that the upstream offers every duration, which a later resolver must verify.
- `court_preferences` has at most 16 entries. Each semantic key is unique and must exist in the selected catalog version. `priority` must have exact JSON type integer (never bool), be unique, and form contiguous values 1..N; the canonical array is sorted by priority. It may be empty only when `allow_any_court_in_venue=true`; otherwise at least one explicit court preference is required.
- `fallback_policy` accepts exactly two boolean fields and `allowed_start_time_range`. Booleans require exact JSON boolean type. If `allow_time_shift=false`, the range must be null. If true, the range is required with inclusive `start`/`end` exact `HH:MM`, start not after end, and it must contain every explicit preferred time. The shift baseline is always `preferred_start_times[0]`; duration never changes.
- `price_ceiling_minor` is null or exact JSON integer (never bool/float), from 0 through `Number.MAX_SAFE_INTEGER`, and is accepted only when the deployment currency/exponent pair exists. The browser accepts a decimal string, converts with digit-string/BigInt arithmetic, checks the safe-integer limit, and only then sends the integer; it never multiplies a floating-point value to derive minor units.
- `target_date` must be a real ISO date and not before the current business-local date. Plan creation is allowed for any later date; query eligibility remains independently limited to current D through D+2.
- Canonical JSON uses UTF-8, sorted keys, compact separators, and no floats; its SHA-256 covers both ReservationIntent and the interpretation snapshot.
- `PlanService.create_plan(user_id, payload, now_utc_ms) -> PlanDTO`, `list_plans(user_id) -> tuple[PlanDTO, ...]`, `get_plan(user_id, plan_id) -> PlanDTO`, `list_revisions(user_id, plan_id) -> tuple[PlanRevisionDTO, ...]`, and `update_plan(user_id, plan_id, base_version, payload, now_utc_ms) -> PlanDTO` are the only plan write/read interfaces. The service derives `today_business_date` from the injected clock and `BookingWindowPolicy`.
- Create and update use short `BEGIN IMMEDIATE` transactions. Every lookup binds `user_id`. For updates, the transaction first reads the owned plan and compares `base_version`; stale versions return 409 even if the submitted content would normalize to the current intent. Only after the version matches may identical normalized content return a no-op without a new revision. Otherwise append a revision and advance the pointer/version atomically.
- Editing an existing plan inherits its stored timezone/currency/catalog interpretation snapshot. The server policy uses that context for the existing plan; new plans use current configuration. A changed deployment configuration cannot reinterpret existing plans; V1 has no in-place settings migration.

- [ ] **Step 1: Write failing strict-schema and service tests**

  Cover exact type checks including booleans in every integer field; 16 KiB body limit; preferred-time count/order/duplicates; duration limits and increments; court count/key/priority/empty-list combinations; fallback field/type/range/baseline combinations; exact minor-unit ceiling and currency/exponent availability; unknown sensitive fields; stable context/hash snapshots across config/catalog changes; same-plan current-pointer consistency; transaction version check before no-op; atomic revision append; rollback; and cross-user not-found behavior.

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

- Register `GET/POST /api/plans`, `GET/PATCH /api/plans/<plan_id>`, `GET /api/plans/<plan_id>/revisions`, and `GET /api/plans/options?catalog_version=...`; the server accepts only current or retained catalog versions and returns semantic choices without upstream identifiers.
- Register `GET /api/booking-window?target_date=YYYY-MM-DD`; it calls only BookingWindowPolicy and never contacts upstream. It uses active configuration for a new plan, reports eligibility only for current D..D+2, shows 07:30 as estimated, always returns `can_book=false` and `can_pay=false`, and accepts no confirmed-open value from the client. Existing plan DTOs calculate display-window facts from that revision's saved timezone context.
- All plan endpoints require a valid application Session; POST/PATCH require CSRF and strict JSON field allowlists. PATCH requires positive `base_version` with exact JSON integer type; bool is rejected.
- Cross-user and missing IDs both return non-disclosing 404. Invalid intent returns 400; stale version returns 409; unauthenticated and CSRF behavior reuses existing application contracts.
- DTOs return semantic fields, server-side version/revision IDs, the immutable interpretation context (business timezone, currency/exponent, catalog version, and label snapshots), and query-window information only. They never return a Token, account fingerprint, venue query node ID, availability, price quote, array index, or coordinate.

- [ ] **Step 1: Write failing route and isolation tests**

  Test unauthenticated 401, mutation CSRF 403, create/list/get/update/revision history, stale 409, unknown fields 400, missing/cross-user identical 404, catalog option projection without node IDs, exact D..D+2 eligibility, false booking/payment flags, no client-settable confirmed-open field, and absence of any upstream transport call.

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
- Form fields map only to ReservationIntent and follow the exact list/count/type/range constraints above. Booking type and duration remain separate controls. Court fallback is limited to the selected venue; time fallback uses the explicit first preferred time as its baseline.
- Price entry is a decimal text field converted to minor units with digit-string/BigInt arithmetic; never compute minor units by multiplying a JavaScript float. Show the revision's snapshotted currency/exponent and timezone, not a changed active configuration.
- Show the server booking-window response. A target outside current D..D+2 is saved as intent but clearly marked non-queryable; saving it does not initiate availability. All plans are intent-only and not availability-verified. Never show a real-open or payment-ready state, stale prices, or coordinates. Do not add a Job/execute button or Agent chat in this slice.
- Save sends the current `base_version`. A 409 keeps the user's draft, offers a reload of the latest revision, and never silently overwrites it.

- [ ] **Step 1: Write failing API-helper, view, and route tests**

  Test credentials-included requests, CSRF on mutations, semantic-only payloads, no node IDs/coordinates, every max-count/type boundary, add/reorder/remove court preferences, same-venue fallback and time baseline/range validation, exact decimal-to-minor conversion without floating-point multiplication, context snapshot display after active config changes, distant-target non-queryability, immutable revision history, version conflict draft retention, and auth/window guard behavior.

- [ ] **Step 2: Run focused frontend tests**

  Run: `cd frontend && npm test -- --run src/api/plans.test.js src/views/PlansView.test.js src/router.test.js`

  Expected: missing plan API/view/route fails after the existing Vitest infrastructure starts normally.

- [ ] **Step 3: Implement the plan API helper and Vue editor**

  Keep all time-window facts server-supplied. The browser may format display values but must not derive T-2, official opening, or availability.

- [ ] **Step 4: Run focused frontend tests and production build**

  Run: `cd frontend && npm test -- --run src/api/plans.test.js src/views/PlansView.test.js src/router.test.js`

  Then run: `cd frontend && npm run build`

  Expected: focused tests pass and Vite produces a successful production build.

- [ ] **Step 5: Commit Task 5**

  Stage exactly `frontend/src/api/plans.js`, `frontend/src/api/plans.test.js`, `frontend/src/views/PlansView.vue`, `frontend/src/views/PlansView.test.js`, `frontend/src/router.js`, `frontend/src/App.vue`, `frontend/src/views/HomeView.vue`, and `frontend/src/router.test.js`. Commit as `feat: add manual reservation plan editor`.

## Task 6: Full Acceptance and Git Integration

**Files:**

- Modify only Task-owned files if acceptance reveals a defect; keep each fix in its owning Task commit where practical.
- Update this plan's task checkboxes and status only after evidence is available.

**Interfaces:**

- Schema version 5 startup remains read-only; migrations run only through the explicit migration command.
- Before applying migration 0005, recheck the current branch manifest and any configured database history. A non-v4 base or checksum mismatch stops this Task.
- All tests use temporary SQLite databases and synthetic catalog/intent values. No test reads `.env` or `req/`, and no real upstream request is made.
- No BookingJob, AvailabilityService query, Agent, LLM Provider, booking, payment, or Tailscale behavior appears in the result.

- [ ] **Step 1: Review full diff and exact Task commit contents**

  Confirm every Task commit includes its listed source, tests, and required config. Confirm `.env`, `req/`, databases/WAL, logs, temp preview artifacts, and generated frontend output are absent.

- [ ] **Step 2: Run full offline acceptance**

  Run: `conda run -n test python -m unittest discover -s backend/tests -v`

  Run: `cd frontend && npm ci && npm test -- --run && npm run build`

  Also run `git diff --check`, version-5 migration/checksum readiness tests, and a test-source audit confirming no external upstream call.

- [ ] **Step 3: Synchronize with local main**

  Recheck `main`. Rebase `feature/03-reservation-intent` only if main advanced, then repeat complete acceptance.

- [ ] **Step 4: Record acceptance without a feature commit**

  Task 6 is integration/acceptance-only and produces no feature commit. If a durable acceptance record is required, make it a separate documentation-only commit with an exact file list; do not create an empty commit or include unrelated files.

- [ ] **Step 5: Obtain explicit integration approval**

  After implementation review and passing acceptance, present the diff and wait for the user's explicit approval before merging or tagging. Only then may the primary checkout run `git merge --ff-only feature/03-reservation-intent`, verify `main`, create `v1-reservation-intent`, and remove this worktree/branch. No merge or tag occurs before that approval.

## Follow-On Plan Boundaries

The next separately reviewed plan may add the Planning Agent and complete OpenAI-compatible Provider configuration on top of the same PlanService. Live availability and the UpstreamContractAdapter, Credential booking profile, BookingJob/Worker, preparation queues, createBooking, payment, and Tailscale remain later stages. No direct Agent writes, CAPTCHA bypass, or upstream rate-limit evasion is allowed.
