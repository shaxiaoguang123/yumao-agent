# V1 Reservation Intent and Plan Management Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **Plan status:** V1 Reservation Intent and Plan Management / Ready for Review

**Goal:** Add user-owned manual booking plans with immutable semantic `ReservationIntent` revisions, optimistic locking, and a Vue editor, while keeping all upstream execution outside this phase.

**Architecture:** Extend the current Flask/Vue/SQLite identity and Credential foundation with a user-scoped `BookingPlan`, append-only `PlanRevision`, strict intent validation, and one `PlanService` used by both the manual API and any later Planning Agent. Add a pure business-time booking-window policy for date display; this phase does not query availability or create jobs.

**Tech Stack:** Python 3.12, Flask, `sqlite3`, existing project dependencies, Vue 3, Vite, Vitest, and Conda `test`.

**Spec:** [V1 Final Architecture Spec](../specs/2026-10-07-multiuser-booking-design.md), especially sections 3, 6, 9, 10, 13, and 14.

## Scope of This Plan

This is the manual-plan foundation slice of the semantic planning stage. It implements creating, viewing, editing, and reviewing immutable plan revisions. The data model and `PlanService` are the shared persistence boundary that a later Planning Agent must use.

Planning Agent, LLM Provider settings, live AvailabilityService queries, BookingJob, Worker, preparation queues, booking, payment, and Tailscale are explicitly deferred to separate reviewed plans. The editor must not imply that a saved intent is available or scheduled for execution.

## Git and Worktree Boundary

- Work only in `/Users/sha/Document/worktree-codex/reservation-intent-plan/yumao-agent` on `feature/03-reservation-intent`; do not develop on `main`.
- The feature branch starts from the reviewed `main` commit tagged `v1-credential-token-lifecycle`. Preserve the primary checkout's local `.env`, uncommitted local-run note, three unrelated untracked files, and running preview servers.
- Every Task ends in a separate commit. Stage only the exact files listed by that Task; never use `git add .`, `git clean`, reset, or broad staging.
- Never commit `.env`, `req/`, database/WAL files, preview artifacts, Tokens, real personal data, or generated frontend assets. Read `req/` only for Task 0, in memory, from the primary checkout; do not copy captures into the worktree.
- No real upstream requests are permitted. All tests use temporary databases and synthetic catalog values.
- After plan approval and implementation, sync with the latest local `main`; rebase if it advanced, then run all backend tests, frontend tests, production build, `git diff --check`, and migration/checksum checks. Integrate with `git merge --ff-only feature/03-reservation-intent`, then create `v1-reservation-intent` on verified `main` and remove the feature branch/worktree. No Git remote is configured.

## Global Constraints

- Preserve Flask + Vue + SQLite and the existing server-side Session, CSRF, and SQL-level `user_id` isolation.
- BookingPlan describes only the user's semantic intent. A PlanRevision stores an immutable canonical snapshot and hash; it never stores availability, a historical court `nodeid`, array indexes, `coordinatesList`, or a historical price.
- Target date is interpreted in the configured IANA `BOOKING_TIMEZONE`, default `Asia/Shanghai`; browser and host time zones do not determine booking windows.
- Query-window calculation is exactly target date `T - 2 days at 00:00` in the business time zone. The estimated opening is `T - 2 days at 07:30`; it is display-only until a later validated upstream response confirms the actual opening. `can_book`/`can_pay` describe time-window facts only and are not execution authorization; this phase adds no booking or payment operation.
- Venue scope and court preferences are semantic choices. Any venue query identifier embedded in a server-side intent comes only from the sanitized, versioned catalog established by Task 0; clients cannot submit arbitrary upstream identifiers.
- Reject unknown intent fields, including Credential, Job, payment, Token, availability, price quote, upstream court/time identifiers, indexes, or coordinates.
- No Agent or LLM code is added in this slice. Later Agent changes must be reviewed by the user and persisted by the same `PlanService`, with no direct SQL write path.
- Do not change the Credential implementation, read `.env` in tests, contact the upstream service, or use old Python booking code as protocol evidence.

## Review Focus

- Client-supplied or stale venue/court identifiers must never be persisted as trusted execution facts; test that intent input accepts catalog keys only and the server resolves the query scope.
- A stale plan version must not overwrite a newer revision; test concurrent/stale `base_version` updates and exact 409 behavior.
- Cross-user plan IDs must be indistinguishable from missing plans; verify SQL queries bind the authenticated `user_id`.
- Time-window boundaries must use business-local calendar dates, including UTC midnight and the exact T-2 00:00 edge; test before, at, and after the boundary.
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

- Evidence identifies which observed value is the top-level venue query scope and separates it from per-court `nodeList[].nodeid`.
- Record field relationships, sample scope, venue/court display semantics, and evidence limits. Keep real query-scope identifiers only in the server-side catalog source; do not copy them into test fixtures or the evidence note. Never record Token, identity/profile values, full payloads, user dates, prices, orders, or raw capture text.
- If local evidence cannot establish a venue mapping or supported semantic choice, stop this Task and report the missing field; do not substitute `DEFAULT_NODEID` from legacy Python code or invent a value.

- [ ] **Step 1: Inspect the local official source and matched captures in memory**

  Confirm the venue query-scope field and its relation to court-level identifiers. Keep output limited to field names and safe semantic catalog entries.

- [ ] **Step 2: Write the sanitized catalog evidence**

  Add the evidence note with sample scope, observed mapping, and unresolved limits. Verify it contains no capture body or personal/secret value.

- [ ] **Step 3: Commit the evidence**

  Stage only `docs/superpowers/evidence/2026-10-08-booking-plan-catalog.md` and commit as `docs: record booking plan catalog evidence`.

## Task 1: Business-Time Policy and Safe Catalog

**Files:**

- Modify: `backend/settings.py`.
- Create: `backend/booking_window.py`, `backend/plans/__init__.py`, `backend/plans/catalog.py`.
- Test: `backend/tests/test_settings.py`, `backend/tests/test_booking_window.py`, `backend/tests/test_plan_catalog.py`.

**Interfaces:**

- `load_settings(env) -> AppSettings` adds `booking_timezone_name`, defaulting to `Asia/Shanghai`, and validates it with `zoneinfo.ZoneInfo`; invalid IANA zones fail fast.
- Booking currency is deployment-owned, never user-selected. Add optional `BOOKING_CURRENCY_CODE` and `BOOKING_CURRENCY_MINOR_UNIT_EXPONENT` as an all-or-none pair; validate the code as three uppercase ASCII letters and the exponent as an integer from 0 through 4. If absent, plans may omit `price_ceiling_minor`, but a non-null ceiling cannot be entered or presented as a converted major-unit amount.
- `BookingWindowPolicy.business_date_at_utc(now_utc_ms: int) -> date`, `queryable_target_dates(now_utc_ms: int) -> tuple[date, date, date]`, and `describe(target_date: date, now_utc_ms: int, confirmed_open_at_utc_ms: int | None = None) -> BookingWindowState` use only `ZoneInfo(BOOKING_TIMEZONE)`. The state returns business timezone, target date, `query_open_at_utc_ms`, display-only estimated open at T-2 07:30, nullable confirmed open, `can_query`, `can_book`, `can_pay`, and a stable reason code. `can_book` and `can_pay` are false until a validated upstream opening time is supplied and reached.
- `VenueCatalog.list_options() -> tuple[VenueOption, ...]` exposes only semantic keys and display labels to the browser. Server-side resolution maps a selected `venue_key` to the exact query scope read from the local Task 0 source; the evidence note itself contains no real identifier.

- [ ] **Step 1: Write failing timezone and catalog tests**

  Test default `Asia/Shanghai`, invalid timezone rejection, exact current three-date query window, UTC instants immediately before/at/after T-2 local midnight, estimated 07:30, confirmed-open precedence, `can_book=false` and `can_pay=false` without a confirmed time, all-or-none currency settings, valid exponent bounds, and that catalog DTOs never return query node IDs.

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
- Revisions are append-only. The migration adds database guards against revision update/delete; the mutable plan row may only advance its current-revision pointer and version through PlanService. Creating the plan and its first revision must satisfy the deferred pointer constraint before commit.

- [ ] **Step 1: Write failing migration/readiness tests**

  Test fresh version-5 migration, the exact required columns/constraints, same-plan/user current-revision pointer enforcement, cross-user composite foreign-key rejection, revision update/delete rejection, checksum mismatch failure, and preservation of existing users and Credential rows.

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

- `parse_reservation_intent(payload: Mapping[str, object], *, today_business_date: date, catalog: VenueCatalog, currency_code: str | None, minor_unit_exponent: int | None) -> ReservationIntent` rejects unknown keys and returns a normalized immutable value.
- The accepted intent fields are `target_date`, `venue_key`, `preferred_start_times`, `duration_minutes`, semantic `booking_type`, ordered `court_preferences`, `fallback_policy`, and nullable `price_ceiling_minor`. The server resolves `venue_key` into the immutable stored query-scope mapping and label snapshot.
- Validate real ISO dates (not past in the business timezone), unique valid HH:MM start preferences, positive integer duration, catalog-supported semantic types/court keys, unique one-based priorities, explicit fallback booleans, a valid inclusive allowed-time range when time shift is enabled, and a non-negative integer price ceiling only when currency configuration exists. Reject client-supplied node IDs, coordinates, availability, Credential, Job, payment, and unknown fields.
- Canonical JSON uses UTF-8, sorted keys, compact separators, and no floats; its SHA-256 is stored with each revision.
- `PlanService.create_plan(user_id, payload, now_utc_ms) -> PlanDTO`, `list_plans(user_id) -> tuple[PlanDTO, ...]`, `get_plan(user_id, plan_id) -> PlanDTO`, `list_revisions(user_id, plan_id) -> tuple[PlanRevisionDTO, ...]`, and `update_plan(user_id, plan_id, base_version, payload, now_utc_ms) -> PlanDTO` are the only plan write/read interfaces. The service derives `today_business_date` from the injected clock and `BookingWindowPolicy`.
- Create and update use short `BEGIN IMMEDIATE` transactions. Every lookup binds `user_id`. Updates compare `base_version`, append a revision, and advance the pointer/version atomically; stale versions raise a typed conflict mapped to HTTP 409. Identical normalized updates return the current revision without creating a duplicate.

- [ ] **Step 1: Write failing strict-schema and service tests**

  Cover valid intents on today/future dates, business-date boundaries, Unicode/duplicate semantic keys, malformed dates/times, invalid fallback combinations, missing currency with a price ceiling, unknown execution-sensitive fields, canonical hash stability, same-plan current-pointer consistency, atomic revision append, no-op update, stale version conflict, rollback, and cross-user not-found behavior.

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

- Register `GET/POST /api/plans`, `GET/PATCH /api/plans/<plan_id>`, `GET /api/plans/<plan_id>/revisions`, and `GET /api/plans/options`.
- Register `GET /api/booking-window?target_date=YYYY-MM-DD`; it calls only BookingWindowPolicy and never contacts upstream.
- All plan endpoints require a valid application Session; POST/PATCH require CSRF and strict JSON field allowlists. PATCH requires `base_version`.
- Cross-user and missing IDs both return non-disclosing 404. Invalid intent returns 400; stale version returns 409; unauthenticated and CSRF behavior reuses existing application contracts.
- DTOs return semantic fields, server-side version/revision IDs, query-window information, and configured currency metadata only. They never return a Token, account fingerprint, venue query node ID, availability, price quote, array index, or coordinate.

- [ ] **Step 1: Write failing route and isolation tests**

  Test unauthenticated 401, mutation CSRF 403, create/list/get/update/revision history, stale 409, unknown fields 400, missing/cross-user identical 404, catalog option projection without node IDs, booking-window T-2 boundaries, and absence of any upstream transport call.

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
- Form fields map only to ReservationIntent: target date, server catalog venue, preferred start times, duration, booking type, ordered semantic court preferences, authorized venue/time fallback range, and optional price ceiling in configured deployment currency.
- Show the booking-window response and clearly label the plan as intent-only and not availability-verified. Do not display stale prices or coordinates. Do not add a Job/execute button or Agent chat in this slice.
- Save sends the current `base_version`. A 409 keeps the user's draft, offers a reload of the latest revision, and never silently overwrites it.

- [ ] **Step 1: Write failing API-helper, view, and route tests**

  Test credentials-included requests, CSRF on mutations, semantic-only payloads, no node IDs/coordinates, add/reorder/remove court preferences, fallback/time-shift validation, currency-aware price ceiling display, window status messaging, immutable revision history, version conflict draft retention, and auth guard behavior.

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

- [ ] **Step 4: Fast-forward integrate and tag**

  From the primary checkout, merge with `git merge --ff-only feature/03-reservation-intent`; verify `main`, create `v1-reservation-intent`, and remove the worktree/branch only after the unique files and untracked user data are confirmed safe.

## Follow-On Plan Boundaries

The next separately reviewed plan may add the Planning Agent and complete OpenAI-compatible Provider configuration on top of the same PlanService. Live availability and the UpstreamContractAdapter, Credential booking profile, BookingJob/Worker, preparation queues, createBooking, payment, and Tailscale remain later stages. No direct Agent writes, CAPTCHA bypass, or upstream rate-limit evasion is allowed.
