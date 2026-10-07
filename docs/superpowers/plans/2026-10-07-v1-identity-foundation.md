# V1 Identity and App Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Establish the V1 Flask/Vue application entry points and deliver invite-only registration, application login, revocable server-side sessions, and the SQLite identity foundation.

**Architecture:** Keep the recovered single-user backend as an isolated legacy reference while the new V1 Flask app is assembled from an app factory and blueprints. Use Python's `sqlite3` for durable identity/session state and Vue 3 with Vite for the separate frontend. This plan stops before Credentials, booking plans, upstream calls, Worker jobs, Agent tools, and Tailscale deployment.

**Tech Stack:** Python 3.12, Flask, SQLite (`sqlite3`), `hashlib.scrypt`, Vue 3, Vite, Vitest, and the existing Conda `test` environment.

**Spec:** [V1 Final Architecture Spec](../specs/2026-10-07-multiuser-booking-design.md)

## Global Constraints

- Keep Flask API + Vue + SQLite + lightweight Worker; do not add Redis, Celery, PostgreSQL, multi-node scheduling, or microservices.
- All authenticated domain-resource SQL reads and writes must include the current `user_id` in the database query. Session bootstrap resolves the principal only from the hashed opaque cookie and a join to the user row; admin operations use explicit admin authorization.
- Use a revocable server-side Session; the browser cookie contains only a random opaque Session ID, and SQLite stores only its hash.
- Passwords use scrypt; invitations are high-entropy, single-use, expiring, and redeemed atomically.
- Cookie-authenticated mutations require a session-bound CSRF token and configured Origin/Referer validation.
- Do not log passwords, Session IDs, CSRF tokens, invitation codes, cookies, Authorization headers, or request bodies.
- Keep `.env`, `req/`, runtime logs, databases, extracted bundles, binaries, and generated frontend assets out of Git.
- Do not call upstream booking, payment, or profile endpoints in this plan.
- Migrations run from one explicit command/process; Flask API startup does not apply migrations implicitly.

## Review Focus

- Concurrent redemption of one invitation must create at most one account; test both sequential reuse and simultaneous redemption.
- A copied or revoked Session cookie must not authenticate; test logout, expiry, and server-side revocation.
- Login, registration, and other cookie-authenticated mutations must reject disallowed Origin/Referer or missing/invalid CSRF as applicable.
- User A must not be able to use a Session or identity resource belonging to User B; scope the SQL query itself and test with two users.
- Every SQLite connection must enforce foreign keys and busy timeout, while migrations remain repeatable and preserve existing rows.

---

## File Layout for This Plan

- `backend/app.py`: new V1 `create_app` factory and blueprint registration.
- `backend/legacy_app.py`: the recovered single-user Flask entry point, retained for reference and excluded from the V1 app's route registration.
- `backend/settings.py`: explicit runtime settings and exact allowed web origins.
- `backend/db.py` and `backend/migrations/`: SQLite connection policy and ordered schema migrations.
- `backend/auth/`: password, Session, invitation, rate-limit services, and immutable auth result types.
- `backend/api/`: authentication, admin invitation, and health blueprints.
- `backend/cli.py` and `backend/migrate.py`: first-admin creation and explicit migration commands.
- `backend/tests/`: standard-library `unittest` coverage for the Flask API and SQLite behavior.
- `frontend/`: new Vue/Vite source; `frontend/dist/` remains generated output and is not tracked.

## Task 1: Separate the V1 Flask App from the Recovered Legacy Entry Point

**Files:**

- Create: `backend/legacy_app.py` by preserving the current recovered `backend/app.py`.
- Modify: `backend/app.py` to define the V1 app factory.
- Create: `backend/settings.py`
- Create: `backend/api/__init__.py`
- Create: `backend/api/health.py`
- Test: `backend/tests/test_app_factory.py`

**Interfaces:**

- `create_app(config: Mapping[str, object] | None = None) -> Flask` constructs an app using injected test/runtime configuration and registers only V1 blueprints.
- `AppSettings` contains `database_path`, `app_env`, `allowed_origins`, `session_cookie_name`, `session_ttl_seconds`, `sqlite_busy_timeout_ms`, `login_fail_limit`, `login_window_seconds`, `register_attempt_limit`, and `register_window_seconds`.
- `load_settings(env: Mapping[str, str] | None = None) -> AppSettings` reads explicit environment settings; tests inject values and never load `.env`. Defaults are `DATABASE_PATH=instance/yumao.sqlite3`, `SESSION_COOKIE_NAME=yumao_session`, `SESSION_TTL_SECONDS=86400`, `SQLITE_BUSY_TIMEOUT_MS=5000`, `LOGIN_FAIL_LIMIT=10`, `LOGIN_WINDOW_SECONDS=900`, `REGISTER_ATTEMPT_LIMIT=10`, `REGISTER_WINDOW_SECONDS=3600`, and development origin `http://localhost:5173`. Production requires an explicit `APP_ALLOWED_ORIGINS` list.
- `health_bp` exposes `GET /api/health` with a minimal `{ "status": "ok" }` response.
- The legacy module remains importable for reference but is never imported or registered by `create_app`.

- [ ] **Step 1: Write failing app-factory tests**

  Add `test_create_app_uses_injected_database_path`, `test_health_endpoint_is_public_and_minimal`, and `test_v1_app_does_not_register_legacy_mutation_routes`. Assert the injected test path is used, health returns status 200 with only the documented status field, and `/api/run` plus `/api/save_plan` are not registered on the V1 app.

- [ ] **Step 2: Run the tests and confirm the expected failures**

  Run: `conda run -n test python -m unittest discover -s backend/tests -p 'test_app_factory.py' -v`

  Expected: the tests fail because the V1 factory and health blueprint do not exist yet.

- [ ] **Step 3: Preserve the current entry point and implement `create_app`**

  Copy the existing single-user `backend/app.py` to `backend/legacy_app.py`, then replace `backend/app.py` with the factory and health blueprint registration. Keep the existing `backend/flow.py` and related modules unchanged; they are reference code and are not reachable from the new V1 app.

- [ ] **Step 4: Re-run the focused tests**

  Run: `conda run -n test python -m unittest discover -s backend/tests -p 'test_app_factory.py' -v`

  Expected: all three tests pass; the legacy routes are absent from the V1 Flask URL map.

- [ ] **Step 5: Commit the app boundary**

  Commit only `backend/app.py`, `backend/legacy_app.py`, `backend/api/`, and `backend/tests/test_app_factory.py` with message `refactor: isolate v1 flask app entry point`.

## Task 2: Add SQLite Connection Policy and Identity Migrations

**Files:**

- Create: `backend/db.py`
- Create: `backend/migrate.py`
- Create: `backend/migrations/0001_identity.sql`
- Test: `backend/tests/test_db.py`

**Interfaces:**

- `connect_database(database_path: Path) -> sqlite3.Connection` sets `row_factory`, `PRAGMA foreign_keys=ON`, and the configured busy timeout on every connection.
- `migrate_database(database_path: Path) -> None` enables WAL, creates `schema_migrations`, applies ordered SQL migrations once, and records each applied version in the same transaction as its schema change.
- `python -m backend.migrate` is the only migration entry point; app startup checks schema readiness but never migrates.

- [ ] **Step 1: Write failing database tests**

  Add `test_each_connection_enables_foreign_keys`, `test_migration_records_version_and_is_repeatable`, and `test_second_migration_run_preserves_inserted_user_rows`. Use a temporary on-disk SQLite file so WAL behavior is exercised.

- [ ] **Step 2: Run the database tests and confirm expected failures**

  Run: `conda run -n test python -m unittest discover -s backend/tests -p 'test_db.py' -v`

  Expected: the tests fail because the connection helper and migration runner do not exist.

- [ ] **Step 3: Implement the connection helper, runner, and initial schema**

  Create `users` (`user_id`, normalized unique username, password hash, role, active/disabled status, UTC timestamps), `sessions` (Session ID hash, `user_id`, expiry/revocation timestamps, CSRF scheme version), `invitations` (invitation-code hash, creator, expiry, redemption/revocation timestamps), and `auth_attempts` with foreign keys, uniqueness constraints, and indexes. Normalize usernames with Unicode NFKC, trim, then casefold; accept 3–64 characters and reject control characters. Session IDs and invitation codes use 32 random bytes encoded with URL-safe base64; only hashes are stored. The initial migration must not include booking-domain tables.

- [ ] **Step 4: Run the database tests**

  Run: `conda run -n test python -m unittest discover -s backend/tests -p 'test_db.py' -v`

  Expected: all three tests pass; `PRAGMA foreign_keys` returns `1`, journal mode is `wal`, and a second migration run makes no schema/data changes or deletes rows inserted after the first run.

- [ ] **Step 5: Commit the SQLite foundation**

  Commit only `backend/db.py`, `backend/migrate.py`, `backend/migrations/0001_identity.sql`, and `backend/tests/test_db.py` with message `feat: add sqlite identity schema and migrations`.

## Task 3: Implement Password, Session, Invitation, and Rate-Limit Services

**Files:**

- Create: `backend/auth/__init__.py`
- Create: `backend/auth/types.py`
- Create: `backend/auth/passwords.py`
- Create: `backend/auth/sessions.py`
- Create: `backend/auth/invitations.py`
- Create: `backend/auth/rate_limit.py`
- Test: `backend/tests/test_auth_services.py`

**Interfaces:**

- `hash_password(password: str) -> str` uses `hashlib.scrypt` with a random salt and versioned parameters encoded in the stored hash.
- `verify_password(password: str, stored_hash: str) -> bool` uses constant-time comparison and rejects malformed hashes safely.
- `UserSummary` and `SessionContext` are frozen dataclasses defined in `backend/auth/types.py`; they contain only user ID, username, role, and Session/CSRF metadata needed by the caller.
- `SessionService.create(user_id: str, now_utc_ms: int) -> tuple[str, str]` returns a one-time opaque Session ID and derived CSRF token while storing only the Session ID hash and CSRF scheme version.
- `SessionService.resolve(session_id: str, now_utc_ms: int) -> SessionContext | None` rejects missing, expired, revoked, disabled-user, or malformed Sessions.
- `SessionService.revoke(session_id: str, now_utc_ms: int) -> bool` revokes the matching Session in SQLite.
- `SessionService.csrf_token_for(session_id: str, scheme_version: int = 1) -> str` derives a session-bound CSRF token using HMAC-SHA256 and the opaque Session ID, then URL-safe-base64 encodes the digest; only the Session ID hash and CSRF scheme version are persisted.
- `SessionService.verify_csrf(session_id: str, supplied_token: str) -> bool` uses constant-time comparison against the derived token.
- `InvitationService.create(created_by_user_id: str, expires_at_utc_ms: int) -> str` returns a one-time high-entropy code and stores only its hash.
- `InvitationService.redeem(code: str, username: str, password_hash: str, now_utc_ms: int) -> UserSummary` atomically consumes an unused, unexpired invitation and creates one user.
- `RateLimitService.check_and_record(event_type: str, normalized_username: str | None, source_ip: str, now_utc_ms: int, limit: int, window_seconds: int) -> bool` atomically counts the current fixed window, records an allowed attempt, rejects attempts at the limit, and prunes expired rows.
- `UserSummary` fields are `user_id: str`, `username: str`, and `role: Literal["admin", "user"]`; `SessionContext` fields are `user: UserSummary` and `csrf_scheme_version: int`.
- `UserSummary` has `user_id`, `username`, and `role`; `SessionContext` has `user: UserSummary` and `csrf_scheme_version`.

- [ ] **Step 1: Write service tests first**

  Add tests for scrypt hash uniqueness and verification, Session opaque-ID storage, Session expiry/revocation, invitation single-use, invitation expiry, two concurrent redemption attempts, and rate-limit window boundaries. The concurrent redemption test must assert exactly one user is created and one redemption succeeds.

- [ ] **Step 2: Run the service tests and confirm expected failures**

  Run: `conda run -n test python -m unittest discover -s backend/tests -p 'test_auth_services.py' -v`

  Expected: the tests fail because the service modules are not implemented.

- [ ] **Step 3: Implement services using SQLite transactions**

  Use `hashlib.scrypt` with a 16-byte random salt, `n=32768`, `r=8`, `p=1`, and a 64-byte derived key; encode the algorithm parameters with the hash for future upgrades. Accept passwords from 12 through 1024 Unicode code points. Use `secrets.token_urlsafe(32)` for Session IDs and invitation codes, and `hmac.new(session_id.encode(), b"csrf-v1", hashlib.sha256).digest()` for a session-bound CSRF token before URL-safe-base64 encoding; persist only the Session ID hash and CSRF scheme version. Use `BEGIN IMMEDIATE` for invitation redemption and persistent rate-limit updates. Set the default absolute Session lifetime to 24 hours through configuration; do not silently slide expiry on reads. Prune rate-limit rows older than 24 hours.

- [ ] **Step 4: Run the service tests**

  Run: `conda run -n test python -m unittest discover -s backend/tests -p 'test_auth_services.py' -v`

  Expected: all tests pass, and no raw Session ID, CSRF token, invitation code, or password appears in persisted rows.

- [ ] **Step 5: Commit the identity services**

  Commit only `backend/auth/` and `backend/tests/test_auth_services.py` with message `feat: add invitation and session services`.

## Task 4: Expose Invite-Only Authentication APIs and the Bootstrap Admin CLI

**Files:**

- Create: `backend/api/auth.py`
- Create: `backend/api/admin.py`
- Create: `backend/api/security.py`
- Create: `backend/cli.py`
- Modify: `backend/app.py`
- Test: `backend/tests/test_auth_api.py`

**Interfaces:**

- `GET /api/auth/session` returns `{authenticated: false}` when unauthenticated, or the minimal current-user summary and a session-bound CSRF token when authenticated.
- `POST /api/auth/register` consumes an invitation and creates an account, returning HTTP 201; the new user then signs in through `/api/auth/login`. It never accepts a role or admin flag from the client.
- `POST /api/auth/login` verifies credentials, rotates to a new server-side Session, and sets an HttpOnly cookie containing only the opaque Session ID with Max-Age equal to the server-side 24-hour Session lifetime.
- `POST /api/auth/logout` revokes the server-side Session and clears the cookie.
- `POST /api/auth/change-password` requires the current password and CSRF token, saves a new scrypt hash, revokes every Session for that user, and clears the current cookie.
- `POST /api/admin/invitations` is admin-only and returns the invitation code exactly once; the database stores only its hash.
- `POST /api/admin/users/{user_id}/disable` is admin-only, disables the target account, and revokes all of its Sessions in one transaction; the target is selected with its ID and role checks in SQL.
- `python -m backend.cli create-admin --username <name>` prompts for the password with `getpass`, creates the first administrator only when no administrator exists, and never accepts a password command-line argument.
- `require_session`, `require_admin`, and `require_csrf` are request guards; every mutation validates configured Origin/Referer, and authenticated cookie mutations also validate `X-CSRF-Token`.
- Successful login/session responses use `{authenticated: true, user: {user_id, username, role}, csrf_token}`; failed login uses a generic 401 response, invalid/expired/redeemed invitation uses a generic 400, forbidden access/CSRF uses 403, and rate limiting uses 429 with `Retry-After`.

- [ ] **Step 1: Write API tests first**

  Add tests for successful registration/login/logout/password change, no public self-registration without an invitation, no client-selected admin role, cookie flags, Session rotation on login, password change revoking every Session, CSRF derivation/verification, CSRF rejection, disallowed Origin rejection, admin-only invitation creation, account disable revoking all Sessions, and first-admin creation only once.

- [ ] **Step 2: Run API tests and confirm expected failures**

  Run: `conda run -n test python -m unittest discover -s backend/tests -p 'test_auth_api.py' -v`

  Expected: the tests fail because the auth blueprints and request guards are not implemented.

- [ ] **Step 3: Implement API and CLI boundaries**

  Use generic error responses for invalid login and invitation redemption. Set `HttpOnly`, `SameSite=Lax`, and `Secure` when `APP_ENV=production`; never return Session IDs or password hashes. Login and invitation redemption use persistent SQLite rate limits: 10 login attempts per normalized username/source-IP pair in 15 minutes, and 10 registration attempts per source IP in one hour. Read source address only from `REMOTE_ADDR`; do not trust forwarded headers in this plan. Store source IP only in the rate-limit table, never in ordinary logs or API responses. These values are configuration defaults and cannot be changed by a normal user. Login and registration require an allowed Origin/Referer even before a Session exists; authenticated cookie mutations additionally require CSRF.

- [ ] **Step 4: Run the API tests**

  Run: `conda run -n test python -m unittest discover -s backend/tests -p 'test_auth_api.py' -v`

  Expected: all tests pass; unauthenticated access cannot create invitations or users without a valid one-time code.

- [ ] **Step 5: Commit the auth API**

  Commit only `backend/api/`, `backend/cli.py`, `backend/app.py`, and `backend/tests/test_auth_api.py` with message `feat: add invite-only authentication api`.

## Task 5: Create the Vue/Vite Authentication Client

**Files:**

- Create: `frontend/package.json`
- Create: `frontend/package-lock.json`
- Create: `frontend/vite.config.js`
- Create: `frontend/index.html`
- Create: `frontend/src/main.js`
- Create: `frontend/src/router.js`
- Create: `frontend/src/api/http.js`
- Create: `frontend/src/stores/session.js`
- Create: `frontend/src/views/LoginView.vue`
- Create: `frontend/src/views/InviteRegisterView.vue`
- Create: `frontend/src/views/HomeView.vue`
- Create: `frontend/src/views/AccountView.vue`
- Create: `frontend/src/App.vue`
- Test: `frontend/src/api/http.test.js`

**Interfaces:**

- The HTTP helper sends `credentials: 'include'`, attaches the in-memory CSRF token to mutations, and refreshes the Session summary from `/api/auth/session` after page load.
- The router provides login, invitation registration, authenticated home, and password-change routes; it never stores Session IDs, CSRF tokens, passwords, or invitation codes in `localStorage`.
- Vite proxies `/api` to the local Flask server; production origin/CORS configuration remains server-side.

- [ ] **Step 1: Write frontend helper tests first**

  Create the package manifest, Vitest configuration, and one failing `http.test.js`. Test that requests include cookies, mutation requests include `X-CSRF-Token`, unauthenticated API errors clear in-memory user state, and no auth value is written to browser storage.

- [ ] **Step 2: Run the frontend tests and confirm expected failures**

  Run: `cd frontend && npm test -- --run`

  Expected: Vitest runs and the assertions fail because the HTTP helper has not been implemented.

- [ ] **Step 3: Implement the Vue/Vite auth shell**

  Add Vue 3, Vue Router, Vite, and Vitest dependencies. Use a single in-memory Session store and the Flask cookie; do not introduce another authentication token format.

- [ ] **Step 4: Run frontend tests and build**

  Run: `cd frontend && npm test -- --run && npm run build`

  Expected: auth-helper tests pass and Vite writes generated assets only to ignored `frontend/dist/`.

- [ ] **Step 5: Commit the frontend auth shell**

  Commit only `frontend/package.json`, `frontend/package-lock.json`, `frontend/vite.config.js`, `frontend/index.html`, `frontend/src/`, and any required test configuration with message `feat: add vue invite login shell`.

## Task 6: End-to-End Foundation Acceptance and Local Run Notes

**Files:**

- Create: `backend/tests/test_auth_flow.py`
- Create: `docs/development/local-run.md`
- Modify: `requirements.txt` only if the executable imports reveal another direct dependency.

- [ ] **Step 1: Install declared backend dependencies in the `test` environment**

  Run: `conda run -n test python -m pip install -r requirements.txt`

  Expected: Flask, Requests, and PyCryptodome are importable in the existing `test` environment; do not print or inspect `.env` values.

- [ ] **Step 2: Add the two-user isolation flow test**

  Create two users through distinct invitations and log in with separate Flask clients. Assert each `/api/auth/session` response is derived only from its cookie and that a client-supplied `user_id` cannot switch the authenticated principal. Assert the test uses only the temporary SQLite database and never calls the upstream Adapter.

- [ ] **Step 3: Run the complete foundation test set**

  Run: `conda run -n test python -m unittest discover -s backend/tests -v`

  Expected: all app-factory, migration, service, API, and isolation tests pass.

- [ ] **Step 4: Build the frontend**

  Run: `cd frontend && npm ci && npm test -- --run && npm run build`

  Expected: lockfile installation, frontend tests, and production build complete successfully.

- [ ] **Step 5: Document the local start sequence**

  Write the exact commands for `conda run -n test python -m backend.migrate`, `conda run -n test python -m backend.cli create-admin --username <name>`, `conda run -n test python -m flask --app backend.app:create_app run --host 127.0.0.1 --port 5000`, and `cd frontend && npm run dev`. Set the Vite proxy target to `http://127.0.0.1:5000`; keep Flask bound to loopback in local development.

- [ ] **Step 6: Review staged files and secret boundaries**

  Confirm the staged diff contains only intended source/docs changes; leave unrelated untracked files untouched. `.env`, `req/`, logs, databases, extracted bundles, PDFs, and executables remain ignored or untracked. Search logs and test output for password, cookie, invitation, and CSRF values without printing those values.

- [ ] **Step 7: Commit the foundation acceptance record**

  Commit only the test and local-run documentation changes with message `docs: record v1 identity foundation workflow`.

## Follow-On Plan Boundaries

These are separate reviewed implementation plans, each merged through a short-lived feature branch after its own acceptance gate:

1. Credential encryption, Token Revision lifecycle, read-only validation, account fingerprint continuity, and user-scoped provider configuration.
2. UpstreamContractAdapter fixtures, BookingWindowPolicy, semantic ReservationIntent/PlanRevision, AvailabilityService, and CandidateResolver.
3. BookingJob snapshots/idempotency, dynamic `official_open`, durable Worker lease, deterministic scheduling, and Credential/account execution locks.
4. PreparationObservation, PreparedQueueRevision, Preparation Agent policy validation, final execution, JobStep/ExternalOrder, reconciliation, cancellation, and payment safety.
5. Booking-plan/task frontend, Agent previews, credential expiry alerts, and private Tailscale deployment after local security acceptance.

The V1 implementation sequence does not create a public endpoint or send live booking/payment requests. Each completed feature branch is fast-forward merged to `main`, deleted after merge, and receives a tag only at a verified milestone.
