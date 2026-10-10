# Booking Plan MVP Implementation Plan

> Use superpowers:executing-plans inline, with one final independent branch review.

**Goal:** Real user-owned unbound draft CRUD and immutable history through Vue, Flask, PlanService and SQLite.
**Architecture:** One plan/revision system; explicit unverified manual contract; no upstream I/O or execution eligibility.
**Tech Stack:** Existing Flask/Python/SQLite, Vue 3 JavaScript, Vite/Vitest and Playwright; Conda test.
**Spec:** ../specs/2026-10-10-booking-plan-mvp.md (user-authorized amendment to the parent design).

## Constraints and review focus

- Preserve main checkout and migration 0001..0004; migrations only on newly created temporary test databases.
- Manual text is never a trusted venue ID. Task 0 PARTIAL / Task 1B BLOCKED remain.
- Context snapshots survive active setting changes; stale edits cannot overwrite current revisions.
- Session/CSRF/user_id protect every API; limit JSON to 16 KiB and strictly validate nested fields/types.
- Fence frontend late results after account, selection, session or request changes. 409 keeps unsaved content.
- Distinguish Mock browser regression from real Flask/SQLite integration. Inspect actual screenshots.

## Task 1: Schema v5

Files: backend/migrations/0005_booking_plans.sql, backend/db.py, backend/tests/test_plan_schema.py; update existing version assertions in test_db.py/test_app_factory.py.
Interfaces: deferred tenant and version bound current-revision pointer, immutable revision UPDATE/DELETE guards; existing migration/checksum engine.
- [ ] Write migration/pointer/rollback/immutability/readiness tests; run unittest discovery pattern test_plan_schema.py. Expected RED: tables/schema missing.
- [ ] Implement 0005/readiness and run focused DB regression. Expected PASS; old migration bytes unchanged.
- [ ] Commit schema and amendment documentation.

## Task 2: PlanService and APIs

Files: backend/plans/{models,validation,service}.py; backend/api/{plans,booking_window}.py; backend/app.py; backend/tests/{test_plan_service,test_plan_validation,test_plans_api}.py.
Interfaces: create_plan/list_plans/get_plan/list_revisions/update_plan with explicit user_id; canonical immutable snapshots and CAS; {intent} create / {base_version,intent} patch.
- [ ] Add strict contract, ownership, concurrency, rollback, context, no-op/stale, API/CSRF/body/window tests; run focused patterns. Expected RED: missing service/routes.
- [ ] Implement bounded pure validation, transactions and blueprints; no legacy plan_validation reuse or network adapter dependency. Expected focused PASS.
- [ ] Commit domain/service/API.

## Task 3: Vue plans

Files: frontend/src/api/plans.js; utils/planForm.js; composables/usePlans.js; components/plans/{PlanManager,PlanForm,PlanHistory,BookingWindowStatus}.vue; views/PlansView.vue; router.js/App.vue/main.js; corresponding Vitest tests.
Component map: PlansView composes PlanManager; usePlans owns requests/epochs/save state; PlanForm owns editable input; PlanHistory displays immutable snapshots; BookingWindowStatus displays server policy. Props down/events up, existing tokens only.
- [ ] Test CRUD, ordering, price conversion, history, distant window, errors, conflict preservation, account/async fencing and guarded route. Expected RED: missing feature.
- [ ] Implement list/create/edit/history and explicit latest preview/adoption; never auto replace 409 draft. Expected Vitest/build PASS.
- [ ] Commit Vue page.

## Task 4: Real browser integration and fixes

Files: backend/tests/plan_browser_server.py; frontend/e2e/{plans-real.mjs,plans-real.vite.config.mjs}; package.json/workflow docs and tests where warranted.
- [ ] Start fresh temp DB/server with explicit synthetic settings, denied upstream transport; real browser uses actual API (no API mocks except deliberate network-fault injection).
- [ ] Login A/create/SQLite proof/refresh/edit/history/409/login B isolation/date windows/empty/network errors; desktop/phone/narrow screenshots and inspect each.
- [ ] Run complete unittest, Vitest/build, existing stable Mock Browser E2E; add separate real integration CI job. Expected all PASS.
- [ ] Independent read-only gpt-6-luna review; fix material findings once with focused RED/GREEN and remaining necessary regression.
- [ ] Commit evidence documentation/fixes, normal push, Draft PR, verify exact-head CI. Do not merge this feature PR.

## Task 5: Handoff

- [ ] Record actual SHA/PR results/tests/screenshots/safe local preview instructions and missing protocol evidence in repository delivery docs and external handoff path requested by user.
- [ ] Verify clean feature tree and unchanged main checkout files; final independent project summary.
