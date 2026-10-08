# V1 Admin Invitation UI Completion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **Plan status:** V1 Admin Invitation UI Completion / Ready for Execution

**Goal:** Give authenticated administrators a safe Vue interface for creating and copying one-time registration invitations through the existing admin API.

**Architecture:** Reuse the existing server-side Session, CSRF-aware HTTP client, admin authorization, invitation service, and `POST /api/admin/invitations` endpoint. Add only the frontend API helper, admin-only route/navigation, creation view, and tests for any uncovered API contract; do not duplicate or expand invitation backend behavior.

**Tech Stack:** Python 3.12, Flask, `sqlite3`, Vue 3, Vue Router, Vite, Vitest, and Conda `test`.

**Spec:** [V1 Identity and App Foundation Implementation Plan](2026-10-07-v1-identity-foundation.md), [V1 Final Architecture Spec](../specs/2026-10-07-multiuser-booking-design.md).

## Verified Existing Implementation

The current source on `main` (`bd12ac8`, `v1-credential-token-lifecycle`) already implements:

- `POST /api/admin/invitations` in `backend/api/admin.py`. It requires a valid Session, server-side `require_admin`, and CSRF. It accepts no expiry option and sets expiry to exactly 24 hours after creation.
- Success is HTTP 201 with `{invitation_code, expires_at_utc_ms}`. The plaintext code is returned only by this creation response.
- `InvitationService.create` generates a high-entropy one-time code, rechecks that the creator is an active administrator inside a SQLite `BEGIN IMMEDIATE` transaction, and persists only the SHA-256 hash.
- The backend already tests admin creation, ordinary-user 403, single-use/hash-only storage, missing/invalid CSRF, and origin rejection in `backend/tests/test_auth_api.py`.
- `GET /api/auth/session` and login already return `user.role`; `createSessionStore` retains it in memory.
- The current frontend declares `@vue/test-utils`, `jsdom`, and `vitest` in `package.json`/lockfile, and `frontend/vitest.config.js` already selects the `jsdom` environment. Component-test infrastructure is present; no dependency/config change is planned.
- The shared HTTP client already sends `credentials: 'include'`, attaches the current CSRF token to mutations, exposes HTTP status/code/kind, clears Session on definitive 401/session-invalid, and preserves the Session on 403/429/5xx/network failures.

The missing behavior is frontend-only: there is no admin invitation API helper, page, route guard, or admin navigation. `App.vue` currently shows the same authenticated navigation to every role; `router.js` has authentication checks but no admin-role guard.

The architecture document mentions invitation list/status and revoke routes, but the current backend has no such endpoints. This plan implements a create-only UI and does not add list, status, revoke, or other admin APIs. The current create endpoint does not emit 409 or 429; the UI handles those statuses safely if returned by an intermediary or a future compatible implementation.

## Git and Worktree Boundary

- Work only in `/Users/sha/Document/worktree-codex/admin-invitations-ui/yumao-agent` on `feature/admin-invitations-ui`; this branch starts from current `main`.
- Keep this iteration separate from `feature/03-reservation-intent`. Preserve that existing worktree and its plan commit. Do not develop on `main`.
- The primary checkout has an uncommitted local-run documentation change and three unrelated untracked files. Preserve them; never use `git clean`, reset, or broad staging.
- Commit Task 1 and Task 2 separately using only their exact file lists. Task 3 is acceptance/integration-only and has no feature commit.
- Do not stage `.env`, `req/`, databases/WAL, logs, browser state, invitation codes, or generated frontend output. Tests use synthetic accounts/codes and mocked HTTP; no real invitation is created.
- After tests and independent review, present the result and wait for explicit user approval before integrating. If approved, fast-forward merge to `main`; create `v1-admin-invitations-ui` only if the user explicitly approves that milestone tag. After this merge, rebase the preserved `feature/03-reservation-intent` branch onto the updated `main` and rerun its complete acceptance before implementing or integrating that feature.

## Global Constraints

- Reuse `createSessionStore` and the shared `httpClient`; do not introduce another Session store, direct unauthenticated fetch path, or frontend-only security claim.
- Frontend role checks only control navigation and rendering. The backend `require_admin` guard remains authoritative and must continue to return 403 for a normal user.
- Invitation validity is fixed at 24 hours by the current backend. Do not add an expiry selector or change backend defaults.
- The plaintext invitation exists only in the creation response and component memory. Never put it in a URL, router state, localStorage, sessionStorage, logs, telemetry, or error text. Clear it when dismissed and when the page unmounts.
- Copying is an explicit user action through the Clipboard API. Do not automatically copy the code.
- Do not automatically retry invitation creation after network/timeout/5xx or an invalid/uncertain response. A request may have committed even when the client did not receive the code; there is no list/recovery endpoint.
- Handle 401, 403, 409, 429, 5xx, and network/timeout errors with safe UI messages. Never render raw response bodies or exception messages.
- No new backend feature, database migration, invitation list/revoke API, user-management screen, BookingPlan, Credential, Worker, LLM, or Tailscale work is in scope.

## Review Focus

- A normal authenticated user cannot see the admin link or render the protected admin view, and direct API calls remain rejected by the backend.
- A successful response shows the code only once, shows the backend-provided expiry, and never persists or logs the plaintext.
- Double-click/in-flight submissions create at most one request. An uncertain response does not cause an automatic replay that might create a second invitation.
- Session-invalid 401 clears in-memory authentication; 403, 409, 429, 5xx, and network errors do not falsely report logout.
- Error rendering must not echo invitation codes, raw response text, or exception details.

---

## File Layout

- `frontend/src/api/adminInvitations.js`, `adminInvitations.test.js`: helper over the existing authenticated HTTP client and its request-contract tests.
- `frontend/src/views/AdminInvitationsView.vue`, `AdminInvitationsView.test.js`: one-time create/copy/display flow, expiry explanation, submission/error states, and memory cleanup.
- `frontend/src/main.js`: construct and provide the helper using the existing SessionStore as the HTTP client.
- `frontend/src/router.js`, `router.test.js`: authenticated admin-only route guard using existing `sessionStore.user.role`.
- `frontend/src/App.vue`, `frontend/src/App.test.js`: show admin navigation only for role `admin`.
- `backend/tests/test_auth_api.py`: extend only if required to cover the currently missing unauthenticated 401 and fixed 24-hour expiry response contract. Existing positive/admin-vs-user/CSRF/hash tests remain the source of truth; no backend source change is planned.

## Task 1: Admin Invitation API Helper and Contract Tests

**Files:**

- Create: `frontend/src/api/adminInvitations.js`, `frontend/src/api/adminInvitations.test.js`.
- Modify: `backend/tests/test_auth_api.py` to add only the currently missing unauthenticated 401 and fixed-expiry contract assertions.
- No backend source or migration change.

**Interfaces:**

- `createAdminInvitationApi(client)` requires a client with `request(path, options)`; `create()` sends `POST /api/admin/invitations` with no expiry/body fields and returns only the validated `invitation_code` and safe integer `expires_at_utc_ms`.
- The helper does not cache, log, persist, or retry the code. It uses the supplied SessionStore/shared HTTP client so credentials and CSRF come from the existing implementation.
- Backend contract tests reuse the existing admin-success, user-forbidden, CSRF, origin, and hash-only tests. Add only the missing no-Session 401 and response-expiry 24-hour assertions if they remain absent in the checked-out test file.

- [ ] **Step 1: Write failing helper tests and missing contract assertions**

  Assert the exact path/method/no-body request, validated response shape, and rejection of malformed success payloads. Add only missing backend assertions for anonymous 401 and a backend-provided expiry approximately 24 hours after creation; retain existing tests for administrator 201, ordinary-user 403, CSRF, and hash-only storage.

- [ ] **Step 2: Run focused tests and confirm the helper tests fail**

  Run: `cd frontend && npm test -- --run src/api/adminInvitations.test.js`

  Run: `conda run -n test python -m unittest backend.tests.test_auth_api -v`

  Expected: helper import/assertions fail because the frontend helper does not exist; existing backend behavior and any newly added contract assertions pass.

- [ ] **Step 3: Implement the API helper**

  Reuse `client.request`; do not modify the backend endpoint or send a client-selected expiry.

- [ ] **Step 4: Run focused tests**

  Run the same frontend and backend commands as Step 2. Expected: helper assertions and all auth API tests pass.

- [ ] **Step 5: Commit Task 1**

  Stage exactly `frontend/src/api/adminInvitations.js`, `frontend/src/api/adminInvitations.test.js`, and `backend/tests/test_auth_api.py`. Commit as `feat: add admin invitation API helper`.

## Task 2: Admin Page, Role Guard, and Navigation

**Files:**

- Create: `frontend/src/views/AdminInvitationsView.vue`, `frontend/src/views/AdminInvitationsView.test.js`, `frontend/src/App.test.js`.
- Modify: `frontend/src/main.js`, `frontend/src/router.js`, `frontend/src/router.test.js`, `frontend/src/App.vue`.
- No change to `frontend/src/stores/session.js`; it already retains `user.role`.

**Interfaces:**

- Register `/admin/invitations` as an authenticated admin-only route. After the initial Session refresh, a non-admin is redirected to the home route; an unknown/unavailable role never renders the admin view.
- `App.vue` shows the invitation-management link only when `sessionStore.user?.role === 'admin'`.
- `main.js` creates the helper from the existing SessionStore/shared client and provides it as `adminInvitationApi`.
- The page has no expiry input. It explains the fixed 24-hour lifetime and one-time use, displays the backend expiry timestamp, displays a successful code once in component memory, and offers explicit copy and dismiss actions.
- While a request is pending, disable creation and ignore duplicate submits. After a successful response, another create requires the user to dismiss/acknowledge the displayed code. On an uncertain network/timeout/5xx result, show that creation may have succeeded and do not automatically retry.
- On unmount/dismiss, clear the code from component state. Clipboard failure has a separate safe status and does not log or persist the code.
- Error mapping is status-based: 401 relies on the existing Session invalidation callback; 403 shows access/CSRF failure without clearing Session; 409 and 429 show a safe conflict/rate-limit message without retry; 5xx/network/timeout show a safe uncertain-outcome message. Never render raw error text.

**Preflight gate before Step 1:** The 2026-10-08 repository audit found `@vue/test-utils`, `jsdom`, and `vitest` in package declarations/lockfile and `environment: 'jsdom'` in `vitest.config.js`. Recheck those exact files on the feature branch before writing/running component tests. If any required dependency or DOM setup is missing, stop and add the needed package/config files to Task 2's Files, test, and exact commit list before continuing; do not treat missing infrastructure as a failing product assertion. No dependency change is expected for the audited branch.

- [ ] **Step 1: Write failing route, navigation, and view tests**

  Cover admin-only navigation visibility; admin route allowed after an admin Session refresh; normal user redirected; unknown/unavailable role cannot render the page; backend remains responsible for 403; successful creation displays one code and the 24-hour expiry; explicit copy succeeds/fails safely; dismiss/unmount clears memory; no local/session storage or URL use; double submit invokes one request; and 401/403/409/429/5xx/network/timeout behavior.

- [ ] **Step 2: Run focused frontend tests**

  Run: `cd frontend && npm test -- --run src/views/AdminInvitationsView.test.js src/App.test.js src/router.test.js`

  Expected: the new view and route/navigation assertions fail before implementation.

- [ ] **Step 3: Implement the page and role-gated route/navigation**

  Use the existing SessionStore role and API helper. Do not add invitation list/revoke controls or change the server.

- [ ] **Step 4: Run focused frontend tests**

  Run the same command as Step 2. Expected: view, route, navigation, and error-state tests pass.

- [ ] **Step 5: Commit Task 2**

  Stage exactly `frontend/src/views/AdminInvitationsView.vue`, `frontend/src/views/AdminInvitationsView.test.js`, `frontend/src/App.test.js`, `frontend/src/main.js`, `frontend/src/router.js`, `frontend/src/router.test.js`, and `frontend/src/App.vue`. Commit as `feat: add admin invitation management page`.

## Task 3: Full Acceptance and Git Handoff

**Files:**

- Modify no product files unless a failing acceptance test reveals a defect; any fix belongs in Task 1 or Task 2 with its own exact-file commit.
- No acceptance-only commit. If an acceptance record is requested, create a separate documentation commit with an exact file list.

**Interfaces:**

- The backend feature contract remains `POST /api/admin/invitations` only. No backend source, schema, list, status, or revoke endpoint is added.
- Tests use synthetic admin/user Sessions, fake HTTP responses, fake clipboard, and temporary databases; no real invitation code or user data is created.

- [ ] **Step 1: Review the full diff and exact Task commits**

  Confirm only the files listed in Task 1 and Task 2 changed; no `.env`, `req/`, database/WAL, logs, or generated output is staged. Confirm the backend does not gain a duplicate invitation endpoint.

- [ ] **Step 2: Run full acceptance**

  Run: `conda run -n test python -m unittest discover -s backend/tests -v`

  Run: `cd frontend && npm ci && npm test -- --run && npm run build`

  Run: `git diff --check main...HEAD` and `git status --short`. Expected: all suites and production build pass; the branch diff is whitespace-clean and any remaining local changes are visible; no test uses a real API.

- [ ] **Step 3: Independent review and user approval gate**

  Present the branch diff and results. Do not merge or tag until the user explicitly approves integration.

- [ ] **Step 4: Fast-forward integration after approval**

  Recheck the latest local `main`; rebase this branch if needed and repeat backend tests, frontend tests, production build, `git diff --check main...HEAD`, and `git status --short`. With explicit approval, merge using `git merge --ff-only feature/admin-invitations-ui`. Create `v1-admin-invitations-ui` only if the user explicitly approves that tag. Preserve `feature/03-reservation-intent`; after the admin merge, rebase it onto the new `main` and rerun its full acceptance before implementation or integration.

## Follow-On Boundaries

This plan completes the missing administrator invitation UI only. Backend admin security remains the existing authoritative boundary. Invitation listing/status/revocation, user administration UI, BookingPlan, Credential, BookingJob/Worker, LLM/Agent, payment, real upstream booking, and Tailscale are not included.
