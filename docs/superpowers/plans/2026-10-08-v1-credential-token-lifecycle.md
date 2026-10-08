# V1 Credential and Token Lifecycle Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **Plan status:** V1 Credential and Token Lifecycle Implementation Plan / Ready for Execution

**Goal:** Implement user-owned Credentials and safe Token lifecycle management on the existing Flask/Vue/SQLite identity foundation, including read-only upstream validation, revocable encrypted Token revisions, explicit account binding state, and a shared SQLite request gate.

**Architecture:** Extend the existing Flask app factory, settings, SQLite migration runner, and Vue shell. Add a bounded `getUserInfo` adapter and one service-wide request gate; keep all Credential data scoped to `user_id`, perform upstream validation outside database write transactions, and apply results only after snapshot rechecks. No booking, Worker, Agent, payment, LLM, or Tailscale behavior is implemented here.

**Tech Stack:** Python 3.12, Flask, `sqlite3`, `requests`, existing `pycryptodome`, Vue 3, Vite, Vitest, and Conda `test`.

**Spec:** [V1 Credential and Token Lifecycle Design](../specs/2026-10-07-credential-token-lifecycle-design.md) and [V1 Final Architecture Spec](../specs/2026-10-07-multiuser-booking-design.md)

## Git and Worktree Development Boundary

- Continue in the existing isolated worktree `/Users/sha/Document/worktree-codex/credential-token-lifecycle` on `feature/02-credential-token-lifecycle`; do not create a second worktree and do not develop on `main`.
- The branch is based on current local `main` and already contains the reviewed design history/baseline commits. The primary checkout contains unrelated untracked user files. Preserve them; never use `git clean`, broad staging, or destructive reset.
- Keep all Task commits on this feature branch. Stage exact paths named by each Task; never use `git add .` or include `.env`, `req/`, databases, logs, or generated frontend assets.
- `req/` is ignored and is present only in the primary checkout, not this worktree. Task 0 may read it from the primary checkout in memory; it must not copy it into this worktree. No real upstream requests are allowed in this plan.
- Before final integration, recheck local `main`. If it advanced, rebase this branch onto it and resolve conflicts. Run the complete backend suite, frontend suite, and production build on the rebased branch. Merge with `git merge --ff-only feature/02-credential-token-lifecycle`; do not create a merge commit. After the verified merge, create `v1-credential-token-lifecycle` on `main` and remove the short-lived feature branch/worktree. There is no configured Git remote in this repository; synchronize only with the latest local `main` unless a remote is explicitly configured later.

## Global Constraints

- Preserve Flask + Vue + SQLite and the existing app Session/CSRF/user isolation. Do not add Redis, Celery, PostgreSQL, microservices, a background Worker, or another queue.
- Task 0 is read-only. It inspects only local `req/` captures and available official frontend code. It does not contact the upstream service. Record only allow-listed contract facts and evidence limits; never save or print Tokens, JWT payloads, personal values, raw request/response bodies, or decrypted captures.
- `token_validation_capability` and `account_continuity_capability` are separate. If Token validation is supported but account continuity is not, support one `unresolved` Credential per user, with read-only validation, disable, and delete. Do not block that supported subset because finite samples cannot prove global uniqueness or permanent future stability. Do not guess identity by username, telephone, display name, or fuzzy matching.
- Keep `account_binding_state` at `unresolved`, `confirmed`, or `needs_reconfirmation`. `requires_revalidation`, enabled state, Token expiry, confirmed Token validity, account binding, and latest validation attempt remain separate dimensions.
- One versioned fingerprint HMAC keyring serves account and Token fingerprints using the exact domain separators `upstream-account-v1` and `credential-token-v1`. Keep it wholly separate from the AES-256-GCM encryption keyring. Keyring parsing enforces canonical base64url, exactly 32 decoded bytes, unique key IDs, a valid active key, and no encryption/fingerprint material reuse; it does not infer entropy using printable-byte or fuzzy placeholder tests.
- Use AES-256-GCM with 96-bit nonce, 128-bit tag, and row-bound AAD. Token revisions are immutable except authenticated ciphertext rewrap and secret clearing. Do not persist JWT payloads or raw upstream identity fields.
- All SQLite connections use explicit `busy_timeout_ms`; all Credential SQL queries bind the current `user_id`. Migrations are numbered and immutable. Startup readiness and key-dependency checks are read-only and fail closed.
- Upstream validation uses only the `getUserInfo` read-only contract established by Task 0. Require a fixed allow-listed origin, TLS verification, redirects disabled, finite connect/read timeouts, a monotonic total deadline, streaming, and a strict response-byte limit. The total deadline does not claim to interrupt an already-blocking socket read at an exact instant; its overrun is bounded by one read-timeout interval plus normal scheduling overhead.
- Each upstream validation gets a fresh Requests Session and disables `trust_env`; cookies, netrc auth, and environment proxy settings must not be shared implicitly across users/Credentials. No proxy setting is added in this phase.
- All `getUserInfo` calls share one SQLite-backed gate across every user and Credential. If the evidence-based minimum interval is not configured, validation returns `503 validation_not_configured` and does not persist a submitted Token. Never infer the `getUserInfo` interval from the unrelated approximately 668 ms observation.
- Parse `Retry-After` delta-seconds; parse HTTP-date only if Task 0 evidence requires it and use a standard-library parser. Malformed, negative, overflowing, or unparseable values use the configured fallback; clamp all values to `MAX_UPSTREAM_BACKOFF_SECONDS` and update deadlines with a monotonic maximum.
- Validation follows snapshot → gate/network → conditional write. Do not hold SQLite write transactions across HTTP. Stale/late responses cannot update Credential summaries, bindings, revisions, or a newer gate lease.
- Use only temporary SQLite databases and synthetic test fixtures. Tests do not load `.env`, read `req/`, print secrets, or make real upstream requests. The only use of captured data is Task 0's in-memory, read-only contract audit.
- Keep BookingPlan/ReservationIntent, BookingJob, Credential booking profiles, Worker/locks, Preparation Agent, booking/payment, LLM Provider, and Tailscale out of this implementation.

## Review Focus

- Token-success responses with absent/unapproved identity data remain valid Token checks where the envelope permits; they do not invent an account binding or invalidate an existing binding.
- Same-user creation/promotion races, including an existing disabled Credential and unmatchable `unresolved`/`needs_reconfirmation` rows, cannot bypass the V1 uniqueness gate. Cross-user identity matches are never queried for product disclosure.
- Disable, delete, rotation, keyring changes, and gate lease expiry between snapshot and response make the response stale; late results cannot restore state or release a newer lease.
- Upstream 3xx, malformed JSON, HTTP 200 business failure, unknown success code, oversized response, TLS error, timeout, or slow streaming response fail closed without leaking sensitive values.
- Historical key dependencies differ by purpose: live ciphertext, current Token fingerprint comparison, and non-deleted account fingerprints in `confirmed`/`needs_reconfirmation` retain only their needed key versions.

---

## File Layout for This Plan

- `backend/settings.py`: typed Credential keyrings, fixed upstream origin, validation gate interval, finite HTTP deadlines, response limit, Retry-After fallback/max, and lease safety margin. Secrets/key bytes are excluded from repr and raw values are not copied into Flask config.
- `backend/db.py` and `backend/migrations/0002_credentials.sql`: schema version 2, schema readiness contract, and Credential/revision/observation/audit/shared-gate tables.
- `backend/credentials/keyring.py`: strict JSON/keyring parsing and safe key-version metadata.
- `backend/credentials/tokens.py`: strict JWT `exp` parsing and domain-separated Token/account fingerprint operations.
- `backend/credentials/crypto.py`: AES-256-GCM Token envelope encrypt/decrypt/rewrap with row-bound AAD.
- `backend/credentials/upstream.py`: bounded HTTP transport and versioned `getUserInfo` response adapter.
- `backend/credentials/contracts.py`: typed safe adapter outcomes; ephemeral identity bytes are never serializable or logged.
- `backend/credentials/request_gate.py`: cross-user SQLite gate, attempt allocation, leases, bounded backoff, and owner/epoch fencing.
- `backend/credentials/key_dependencies.py`: read-only startup/maintenance checks for live encryption and fingerprint-key dependencies.
- `backend/credentials/service.py` and `backend/credentials/types.py`: Credential state machine, snapshot/network/conditional-write operations, safe DTOs, and typed service results.
- `backend/api/credentials.py` and `backend/app.py`: user-scoped Credential endpoints and app-factory registration.
- `backend/cli.py` plus `backend/credentials/maintenance.py`: explicit Token ciphertext rewrap/key-dependency maintenance; no user API performs key rotation.
- `backend/tests/test_credential_*.py`: temporary-DB, synthetic-token, fake-transport tests for configuration, migration, crypto, adapter, gate, service, API, and key maintenance.
- `frontend/src/views/CredentialView.vue`, `frontend/src/api/credentials.js`, `frontend/src/router.js`, `frontend/src/App.vue`, `frontend/src/views/HomeView.vue`: add/list/validate/rotate/enable/disable/delete and current-user Token/binding-risk UI.
- `frontend/src/views/CredentialView.test.js` and `frontend/src/api/credentials.test.js`: focused component/API-state tests; no broad snapshot suite.
- `docs/development/local-run.md`: local key generation/configuration, explicit migration, startup, and verification instructions without printing or checking in secret values.

## Task 0: Read-Only Upstream Contract and Evidence Gate

**Files:**

- Read only: ignored `req/` in the primary checkout and available official frontend source.
- Create: `docs/superpowers/evidence/2026-10-08-get-user-info-contract.md` containing only safe facts and unresolved evidence.
- No production code, fixture payload, or live request is created in this Task.

**Interfaces:**

- Evidence output reports `token_validation_capability` and `account_continuity_capability` independently, with observed sample scope and unresolved limits.
- `token_validation_capability` must establish the `POST /service/appointment/appointment/userAddress/getUserInfo` method/path/header/body shape, the known success HTTP/JSON envelope and success/message/resultData combination, and at least one successful known-token observation. The evidence note records that personal fields stay out of persistence/log/API/Agent contexts as a design invariant, not as a claim proven by captures.
- `account_continuity_capability` is true only if the observed identity field is a defensible same-account continuity signal in the available samples and official flow. Do not require proof of global uniqueness or future permanence; explicitly record those remain unproven.
- The request minimum interval is endpoint-specific. If evidence does not identify a safe `getUserInfo` interval, leave the runtime gate unconfigured and keep validation disabled; do not borrow the approximately 668 ms observation, because it was not identified as this endpoint.

- [ ] **Step 1: Inspect only the local capture/source metadata and required in-memory fields**

  Read the local primary-checkout `req/` files in memory. If local capture decryption is required, use only the already-provisioned local environment through a process that never prints or logs the decryption value or decrypted payload. Do not copy ignored captures into this branch or temporary repository files.

- [ ] **Step 2: Record the request and success contract without sensitive values**

  Confirm the observed method/path/header/body shape, HTTP status, JSON envelope, success/message/resultData combination, identity field name and official frontend use. Record invalid-Token response semantics and `getUserInfo` timing only when directly evidenced. Do not include Token values, JWT claims/payload, identity values, raw bodies, cookies, or authorization header contents.

- [ ] **Step 3: Record capability results and stop conditions**

  Write the sanitized evidence note. If `token_validation_capability` is unsupported, stop before Tasks 1–8 and report the missing local evidence; do not make a live request. If Token validation is supported but account continuity is not, set the implementation to unresolved-only capability and continue. If the endpoint-specific request interval is not evidenced, keep `UPSTREAM_GET_USER_INFO_MIN_INTERVAL_MS` unconfigured and preserve the `503` disabled behavior.

- [ ] **Step 4: Review and commit the safe evidence note**

  Run `git diff --check`, inspect the note for sensitive values, and commit only the new evidence note as `docs: record getUserInfo contract evidence`.

## Task 1: Add Credential Settings and Schema Version 2

**Files:**

- Modify: `backend/settings.py`
- Modify: `backend/app.py` to filter raw Credential secret settings from Flask config.
- Modify: `backend/db.py` to set `CURRENT_SCHEMA_VERSION = 2` and verify Credential schema readiness.
- Create: `backend/migrations/0002_credentials.sql`
- Create: `backend/credentials/__init__.py`
- Create: `backend/credentials/keyring.py`
- Create: `backend/tests/support.py`
- Modify: `docs/superpowers/plans/2026-10-08-v1-credential-token-lifecycle.md` to include the specification's 7-day expiry reminder setting and schema-v2 singleton gate readiness assertion.
- Test: `backend/tests/test_settings.py`
- Test: `backend/tests/test_db.py`
- Test: `backend/tests/test_app_factory.py`
- Modify: `backend/tests/test_auth_api.py` to use synthetic Credential settings.
- Modify: `backend/tests/test_auth_flow.py` to use synthetic Credential settings.

**Interfaces:**

- `CredentialKeyring` and strict JSON/base64url parsing live in `backend/credentials/keyring.py`; `AppSettings` exposes two parsed keyrings. Load them from `APP_CREDENTIAL_ENCRYPTION_KEYS`, `APP_CREDENTIAL_ENCRYPTION_ACTIVE_KEY_ID`, `APP_UPSTREAM_FINGERPRINT_KEYS`, and `APP_UPSTREAM_FINGERPRINT_ACTIVE_KEY_ID`. Key material is bytes and excluded from repr. Encryption and fingerprint rings are independent.
- `AppSettings` exposes `token_expiring_soon_window_seconds` from optional `TOKEN_EXPIRING_SOON_WINDOW_SECONDS`, defaulting to exactly 604800 seconds (7 days). It also exposes fixed `upstream_origin` from `UPSTREAM_ORIGIN`, optional `upstream_get_user_info_min_interval_ms` from `UPSTREAM_GET_USER_INFO_MIN_INTERVAL_MS`, `upstream_connect_timeout_seconds` from `UPSTREAM_CONNECT_TIMEOUT_SECONDS`, `upstream_read_timeout_seconds` from `UPSTREAM_READ_TIMEOUT_SECONDS`, `upstream_total_deadline_seconds` from `UPSTREAM_TOTAL_DEADLINE_SECONDS`, `upstream_max_response_bytes` from `UPSTREAM_MAX_RESPONSE_BYTES`, `upstream_retry_after_fallback_seconds` from `UPSTREAM_RETRY_AFTER_FALLBACK_SECONDS`, `max_upstream_backoff_seconds` from `MAX_UPSTREAM_BACKOFF_SECONDS`, and `upstream_lease_safety_margin_seconds` from `UPSTREAM_LEASE_SAFETY_MARGIN_SECONDS`. Require `connect < total`, `read < total`, a positive response limit, a positive safety margin, and fallback no greater than max. Missing endpoint interval means validation is unconfigured; no default interval is invented.
- `backend/tests/support.py` provides `credential_test_settings(database_path: Path) -> dict[str, object]` with deterministic, distinct synthetic 32-byte encryption/fingerprint keys and explicit synthetic transport values. It never reads `.env` or the process environment.
- `0002_credentials.sql` adds `credentials`, `credential_token_revisions`, `credential_validation_observations`, `credential_lifecycle_audits`, and singleton `upstream_request_gate` tables. Store Credential `current_token_revision_id`, three-state `account_binding_state`, nullable fingerprint/key/identity-contract fields, `last_confirmed_validation_state`, `last_successful_validation_at_utc_ms`, `requires_revalidation`, and `credential_version`; do not add `validation_summary_revision_id`.
- Token revision rows hold immutable version/exp/fingerprint/initial-validation facts and encrypted envelope metadata. Observation rows hold only safe result enums, status class, attempt order/times, gate owner/epoch, and snapshot/apply state. Neither rows nor indexes contain raw identity or Token data.
- Composite foreign keys include `user_id`. Indexes support user-scoped list/current-revision lookups, same-user fingerprint checks across retained key versions, and gate lease state. There is no cross-user account-fingerprint UNIQUE constraint.

- [ ] **Step 1: Write failing keyring settings tests**

  Add a test-only `credential_test_settings` helper and update the existing auth API/flow app fixtures to use synthetic keyrings. Add tests for valid canonical 32-byte keys, malformed/noncanonical base64url, wrong decoded lengths, duplicate IDs rejected before mapping creation, empty keyring, missing active ID, active ID absent, key-ID validation, cross-ring material reuse, repr/Flask-config redaction, and accepted printable bytes (no entropy heuristic). Add tests for timeout ordering, response-size bounds, Retry-After fallback/max, optional upstream interval parsing, the 604800-second default/positive configured Token reminder window, and invalid settings.

- [ ] **Step 2: Write failing schema-v2 migration/readiness tests**

  Test all required Credential columns/tables, state CHECK constraints, same-user composite foreign keys, revision uniqueness, the single seeded `getUserInfo` gate row required for readiness, `foreign_key_check`, and `CURRENT_SCHEMA_VERSION=2`. Confirm the existing `0001_identity.sql` remains byte-for-byte unchanged and old identity data survives migration. Key-dependency startup tests are owned by Task 5, after the dependency checker exists.

- [ ] **Step 3: Run the focused tests and confirm expected failures**

  Run focused tests with `conda run -n test python -m unittest discover -s backend/tests -p '<test_file>.py' -v` for `test_settings.py`, `test_db.py`, `test_app_factory.py`, `test_auth_api.py`, and `test_auth_flow.py`.

  Expected: existing Identity Foundation tests continue to pass; new Credential settings and schema assertions fail because the fields, version-2 migration, and readiness checks are not implemented.

- [ ] **Step 4: Implement strict settings and migration**

  Extend `AppSettings` with parsed keyring material and upstream limits; keep all raw keyring configuration out of `Flask.config`. Add `0002_credentials.sql`, update the readiness column/table contract, and preserve explicit migration/checksum behavior. Keep SQL DDL and the new migration file limited to this Task's schema.

- [ ] **Step 5: Run focused tests**

  Run the same five `unittest discover` commands from Step 3.

  Expected: all existing identity tests and new schema/settings tests pass with temporary databases and synthetic config only.

- [ ] **Step 6: Commit the complete configuration/schema unit**

  Stage the exact settings, keyring parser, app-factory, DB/readiness, migration, test settings helper, the named test files, and this plan update. Commit as `feat: add credential schema and settings`.

## Task 2: Implement Token Parsing, Fingerprints, and AES-256-GCM

**Files:**

- Create: `backend/credentials/__init__.py`
- Create: `backend/credentials/tokens.py`
- Create: `backend/credentials/crypto.py`
- Test: `backend/tests/test_credential_tokens.py`
- Test: `backend/tests/test_credential_crypto.py`

**Interfaces:**

- `CredentialKeyring` is immutable and contains key-ID→bytes mapping plus active key ID. Parsing itself does not expose key bytes in repr/errors. Database key-dependency checks are owned by Task 5.
- `parse_token_exp(token: str, now_utc_ms: int, expiring_soon_window_seconds: int = 604800) -> TokenExpiry` inspects only the JWT `exp` value; it never validates a signature or stores the full payload. It rejects bool/NaN/Infinity/out-of-range/overflow/non-exact millisecond values as `expiry_unknown`; valid expired tokens are blocked before dispatch. `exp` within 604800 seconds is `expiring_soon` by default; exact-window boundary behavior is tested.
- `token_fingerprint(token: str, keyring: CredentialKeyring) -> VersionedFingerprint` uses `credential-token-v1`; `account_fingerprint(identity_bytes: bytes, keyring: CredentialKeyring) -> VersionedFingerprint` uses `upstream-account-v1`. Account identity input is exact UTF-8 bytes with unambiguous length/domain framing; never normalize it.
- `CredentialTokenCipher.encrypt(plaintext: bytes, *, user_id: str, credential_id: str, revision_id: str, key_id: str) -> EncryptedTokenEnvelope` and `.decrypt(envelope, same_context) -> bytes` use AES-256-GCM, a fresh 12-byte nonce, 16-byte tag, and AAD binding all row IDs plus key ID.

- [ ] **Step 1: Write failing JWT and fingerprint tests**

  Cover valid `exp`, missing/malformed JWT, bool, NaN/Infinity, numeric range and millisecond conversion boundaries, expiry-at-now, exact 604800-second `expiring_soon` window boundary, exact-byte identity input, domain separation, deterministic fingerprints, and key-version metadata. Service-level current-token comparison behavior is tested in Task 5.

- [ ] **Step 2: Write failing AES-GCM envelope tests**

  Cover round-trip, nonce uniqueness, exact 12-byte nonce/16-byte tag, changed user/Credential/revision/key context, ciphertext/tag tampering, unavailable encryption key, and no plaintext/payload in dataclass repr or errors.

- [ ] **Step 3: Run the focused tests and confirm expected failures**

  Run: `conda run -n test python -m unittest discover -s backend/tests -p 'test_credential_tokens.py' -v`, then repeat with `test_credential_crypto.py`.

  Expected: the new module/interface assertions fail because the Credential token primitives do not exist yet.

- [ ] **Step 4: Implement token primitives and cipher**

  Use Python standard-library JSON/base64/hashlib/hmac plus the existing PyCryptodome AES dependency. Do not implement a custom cipher, unkeyed account hash, printable-byte entropy heuristic, or second fingerprint keyring.

- [ ] **Step 5: Run focused tests**

  Run the same two `unittest discover` commands from Step 3.

  Expected: all synthetic token, malformed-exp, fingerprint, and encryption tests pass without reading environment secrets.

- [ ] **Step 6: Commit the Token primitives**

  Commit only `backend/credentials/tokens.py`, `backend/credentials/crypto.py`, and the two tests as `feat: add credential token cryptography`; `__init__.py` and `keyring.py` were committed in Task 1.

## Task 3: Add the Bounded `getUserInfo` Contract Adapter

**Files:**

- Create: `backend/credentials/upstream.py`
- Create: `backend/credentials/contracts.py`
- Test: `backend/tests/test_credential_upstream.py`

**Interfaces:**

- `UpstreamHttpTransport` is constructed with an injected `session_factory: Callable[[], requests.Session]` and monotonic clock; it creates, configures (`trust_env=False`), and closes one fresh Session per request. Tests supply fakes. `AdapterValidationResult` contains safe Token outcome, optional short-lived identity bytes marked `repr=False`, identity-contract version/capability outcome, HTTP status class, and a bounded Retry-After input. It never contains the raw body or response object.
- `UpstreamContractAdapter.validate_token(token: str) -> AdapterValidationResult` performs only the evidenced read-only `getUserInfo` request. It is reachable only through `CredentialService`, which acquires the shared gate before calling it.
- The fixed HTTPS origin is configured as `UPSTREAM_ORIGIN` and must exactly match the Task 0 allow-listed host; the path is the code-pinned `/service/appointment/appointment/userAddress/getUserInfo`. No user/provider URL is accepted. The request uses POST JSON `{}`, the evidenced `token` auth header, TLS verification, and `allow_redirects=False`.
- Transport streams the body, enforces `upstream_max_response_bytes`, uses finite connect/read timeouts, checks `time.monotonic()` between chunks/before new reads, and closes after total deadline. One active blocking read may overrun by at most its configured read timeout plus scheduling overhead.
- HTTP status plus the exact observed JSON envelope and success/message/resultData combination determines Token validity. Unknown response codes/shapes, unexpected HTTP status, redirects, TLS errors, and transport failures fail closed. A Token-success response with unavailable/unapproved account identity may return valid Token outcome with no identity; it cannot establish a fingerprint.

- [ ] **Step 1: Write failing fake-transport contract tests**

  Use synthetic responses only. Assert method/path/header/body shape without asserting a real Token, TLS verification, redirect disabled, finite timeout tuple, streaming, maximum response bytes, deadline stop/close behavior, exact success envelope, unknown message/schema failure, identity-field absence handling, and that no raw body/header/free-text enters the result or logs.

- [ ] **Step 2: Run the fake-transport tests and confirm expected failures**

  Run: `conda run -n test python -m unittest discover -s backend/tests -p 'test_credential_upstream.py' -v`.

  Expected: contract and transport assertions fail because the adapter does not exist; all tests must use fakes and make zero network requests.

- [ ] **Step 3: Implement bounded transport and contract parsing**

  Use existing `requests`; disable redirects and keep TLS verification on. Stream response bytes and check the monotonic deadline between chunks. Do not add a thread pool/custom socket layer to promise exact interruption of an already-blocked read.

- [ ] **Step 4: Run focused adapter tests**

  Run the same focused discover command from Step 2.

  Expected: all tests use a fake Session/transport and perform zero network access.

- [ ] **Step 5: Commit the adapter**

  Commit the adapter, contract type, and tests as `feat: add bounded getUserInfo adapter`. The current `requests` dependency is already declared; do not change `requirements.txt` unless implementation demonstrates a concrete missing dependency, then include that exact change in this commit.

## Task 4: Implement the SQLite-Backed Global UpstreamRequestGate

**Files:**

- Create: `backend/credentials/request_gate.py`
- Create: `backend/migrations/0003_upstream_gate_started_at.sql`
- Modify: `backend/db.py` to advance schema version to 3 and require the gate-start timestamp/readiness invariant.
- Modify: `backend/tests/test_db.py` and `backend/tests/test_app_factory.py` for schema version 3 and migration 0003.
- Modify: `docs/superpowers/specs/2026-10-07-credential-token-lifecycle-design.md` and this plan to specify persisted original gate start time and transactional preflight fencing.
- Test: `backend/tests/test_credential_request_gate.py`

**Interfaces:**

- `0003_upstream_gate_started_at.sql` adds `active_started_at_utc_ms` to the existing shared gate row with triggers requiring it exactly while a lease is active. Do not edit already-applied migrations `0001_identity.sql` or `0002_credentials.sql`.
- Advance `CURRENT_SCHEMA_VERSION` to 3. Readiness must require the new column and validate gate lease coherence, including exactly one `getUserInfo` row, `lease_owner_id`, `active_validation_attempt_id`, and `active_started_at_utc_ms` present together or all absent.
- `GateOperationContext` is a frozen value with `user_id`, nullable `credential_id`, `operation_kind`, nullable `credential_version_snapshot`, nullable `current_token_revision_snapshot_id`, and nullable `token_revision_id`. It contains no Token or identity values. `GatePreflightDenial` contains only a safe denial code, a schema-allowed attempt result, and an optional schema-allowed account-binding outcome.
- `GateAttemptObservation` carries the exact safe columns in `credential_validation_observations`: attempt/user/credential IDs, operation kind, snapshot version/revision, optional persisted revision ID, start/completion times, safe attempt result/binding outcome/status class, owner/epoch, and apply state.
- `UpstreamRequestGate.acquire(context: GateOperationContext, now_utc_ms: int, preflight_check: Callable[[sqlite3.Connection, GateOperationContext], GatePreflightDenial | None]) -> GateDecision` requires a preflight callback and runs one `BEGIN IMMEDIATE`; it allocates `validation_attempt_id` in request order, invokes the read-only callback on that same SQLite connection under a SQLite authorizer that denies writes, then checks the single `getUserInfo` endpoint interval/backoff/in-flight lease. It returns either a `GatePermit` (`validation_attempt_id`, `owner_id`, `epoch`, `started_at_utc_ms`, `lease_expires_at_utc_ms`, context) or a safe denial/retry seconds. The callback may only read/compare and does not perform I/O. This makes the final credential enabled/version/revision/expiry/binding check atomic with permit creation. Expired-token, disabled/unconfigured, rate-limited, and other no-dispatch outcomes append a safe observation in the same transaction and never create a permit. Missing evidence-based endpoint interval returns unconfigured; it never creates per-user/per-Credential gates.
- `complete_in_transaction(connection: sqlite3.Connection, permit: GatePermit, safe_observation: GateAttemptObservation, now_utc_ms: int, *, upstream_status_code: int | None, retry_after_header: str | None = None) -> GateCompletion` appends the final safe observation, updates bounded backoff, and releases only a matching live owner/epoch as part of the Credential service's final `BEGIN IMMEDIATE` transaction. `mark_uncertain_in_transaction(connection, permit, safe_observation, now_utc_ms) -> GateCompletion` records an uncertain read while retaining the lease until expiry. Late/stale completion is fenced and cannot shorten backoff or release a newer owner.
- Lease expiry is `start + total_deadline + safety_margin`, with safety margin at least one configured read timeout plus cleanup allowance. Persist the original `active_started_at_utc_ms`; lease reclaim uses it when appending the old attempt's stale observation before incrementing epoch.
- Retry-After accepts delta-seconds; HTTP-date is enabled only if Task 0 evidence requires it. Invalid/negative/overflow values use configured fallback. All delays clamp to `max_upstream_backoff_seconds`.

- [ ] **Step 1: Write failing rolling gate/concurrency tests**

  Cover request-order attempt IDs for permit, rate denial, expired-token and unconfigured preflight denial; prove preflight races are rechecked inside the gate transaction; one service-wide lease across user IDs; minimum interval; backoff monotonic max; delta-seconds/date/fallback/malformed/negative/overflow/max-clamp cases; persisted start time used for stale lease-reclaim observation; lease expiry/margin; stale owner/epoch release; late completion; and SQLite serialization using temporary databases.

- [ ] **Step 2: Run gate tests and confirm expected failures**

  Run `conda run -n test python -m unittest discover -s backend/tests -p 'test_credential_request_gate.py' -v`, then repeat with `test_db.py` and `test_app_factory.py`.

  Expected: gate assertions fail because the gate module is absent; schema-v3 assertions fail because migration 0003/readiness are absent and the app still requires schema 2. Existing unrelated identity assertions continue to pass.

- [x] **Step 3: Update the design and plan with the resolved gate fields**

  Added `active_started_at_utc_ms` to the Gate's persisted active request context and specified that Credential snapshot preflight is re-read inside the same acquisition transaction. Preserved the already-approved gate, ordering, timeout, and retry semantics. Committed as `afd01a9`.

- [ ] **Step 4: Implement migration 0003 and schema-v3 readiness**

  Add only `active_started_at_utc_ms` and coherence triggers in a new migration. Update schema readiness and existing migration-upgrade/app-factory tests to require schema version 3 while preserving the immutability/checksum of 0001 and 0002.

- [ ] **Step 5: Run the migration/readiness regression tests and confirm green**

  Run the same `test_db.py` and `test_app_factory.py` commands from Step 2.

  Expected: migration 0003 applies atomically, the existing schema-v2 and identity data remain intact, and app startup fails on schema 2 without applying migration 0003.

- [ ] **Step 6: Implement the gate with explicit transactions**

  Use short SQLite `BEGIN IMMEDIATE` transactions for acquire/complete/reclaim; never hold a write transaction while HTTP is in progress. Gate rows contain only internal IDs and safe metadata, not Token, fingerprints, user profile, or raw headers.

- [ ] **Step 7: Run gate tests**

  Run the same focused `test_credential_request_gate.py` command from Step 2.

  Expected: concurrent attempts produce one permit and stable request-order IDs; no test performs HTTP.

- [ ] **Step 8: Commit the shared gate and migration**

  Commit `request_gate.py`, migration 0003, schema/readiness updates, migration/app-factory test updates, and gate tests as `feat: add shared upstream validation gate`.

## Task 5: Implement Credential Lifecycle Service and Conditional Writes

**Files:**

- Create: `backend/credentials/types.py`
- Create: `backend/credentials/service.py`
- Create: `backend/credentials/key_dependencies.py`
- Modify: `backend/app.py` to initialize one adapter, gate, cipher, and CredentialService with explicit settings.
- Modify: `backend/credentials/upstream.py` and `backend/tests/test_credential_upstream.py` so each validation receives a fresh HTTP Session with `trust_env=False` and no cookie/netrc/proxy state shared across attempts.
- Test: `backend/tests/test_credential_service.py`
- Test: `backend/tests/test_credential_key_dependencies.py`

**Interfaces:**

- `CredentialService.list_for_user(user_id) -> list[CredentialDTO]` and `.get_for_user(user_id, credential_id) -> CredentialDTO | None` are SQL-scoped by `user_id`.
- `.create(user_id, label, token, now_utc_ms) -> CredentialDTO` validates input and checks same-user unmatchable-row/capability gates before dispatch. It does not persist a candidate token until read-only validation succeeds. When continuity is unavailable and user has no non-deleted Credential, it creates only `unresolved`; when approved identity is returned, it compares against all same-user confirmed bindings under retained key versions and rejects matches. If a Token-success response lacks a usable identity, create `unresolved` only when the user has no other non-deleted Credential; otherwise return `credential_account_binding_unresolved` without persisting the candidate.
- `.validate(user_id, credential_id, expected_credential_version, expected_revision_id, now_utc_ms) -> CredentialOperationResult` and `.rotate_token(...)` follow snapshot → gate/network → conditional `BEGIN IMMEDIATE` write. In the final transaction, Credential summary/binding updates, `CredentialValidationObservation` append, gate completion/backoff update, and lease release are atomic. Uncertain reads append a safe result but retain the lease until expiry. Results arriving after disable/delete/rotation/keyring epoch/lease expiry are stale.
- `.set_enabled(...)` leaves account-binding state unchanged; enabling sets `requires_revalidation=true`. `.soft_delete(...)` blocks new use, clears active revision ciphertext and account fingerprint in this Credential-only phase, clears key/contract dependencies, records a safe tombstone/audit event, and does not claim physical SQLite/WAL erasure.
- `needs_reconfirmation` only recovers on successful current-Token validation under the current approved identity contract and constant-time continuity match. Current-Token mismatch preserves the old fingerprint and changes binding to `needs_reconfirmation`; candidate rotation mismatch rejects only the candidate.
- `latest_requested_validation_attempt` is projected by allocated attempt ID; `last_successful_validation_at_utc_ms` remains a separate Credential summary belonging to `current_token_revision_id`. There is no validation-summary revision pointer.
- Startup performs a read-only key-dependency scan. Encryption keys are required for active ciphertext; fingerprint HMAC keys are required only for live account fingerprints and current Token fingerprints still used for equality checks.

- [ ] **Step 1: Write failing service tests using fake adapter and gate**

  Cover create label/token length/control-character boundaries, create success/unresolved/confirmed, no persistence on denied gate/invalid candidate/unknown response, same-user confirmed duplicate conflict including disabled rows, create blocking on same-user unresolved/reconfirmation rows, no continuity capability allowing only one non-deleted row, Token-success with missing identity creating unresolved only for an otherwise empty user, missing-identity conflict when another Credential exists, and confirmed Token-success with missing identity preserving the existing binding. Cover disable/enable orthogonality, Token expiry, rotation same/different/missing identity, same-current-Token `token_already_current` without dispatch/revision, permitted historical Token reuse, unresolved promotion, reconfirmation, current-token mismatch, transient failure non-downgrade, same-transaction summary/pointer changes, latest-requested attempt projection, delete clearing, two-user isolation, and snapshot races.

- [ ] **Step 2: Write failing key-dependency and startup tests**

  Cover missing keys referenced by active ciphertext/current Token/account fingerprints, retained disabled/`needs_reconfirmation` dependencies, inert historical revision/tombstone keys, v1→v2 lazy account-fingerprint rebind on a continuity match, mismatch preservation, current Token comparison under its original key version, and read-only startup failure without database mutation.

- [ ] **Step 3: Run service and key-dependency tests and confirm expected failures**

  Run: `conda run -n test python -m unittest discover -s backend/tests -p 'test_credential_service.py' -v`, then repeat with `test_credential_key_dependencies.py`.

  Expected: the new service/state/ownership/key-dependency assertions fail because the service is not implemented.

- [ ] **Step 4: Implement CredentialService and dependency checks**

  Pass explicit user ID, settings, adapter, gate, and clock time. Do not access Flask request globals from the service. Keep network I/O outside SQLite write transactions. Save only fingerprints/safe enums; never save raw identity or adapter response.

- [ ] **Step 5: Run service and dependency tests**

  Run the same two focused discover commands from Step 3.

  Expected: all tests use temp SQLite, synthetic Tokens and fake upstream outcomes only.

- [ ] **Step 6: Commit the Credential service**

  Commit only service/types/dependency/app wiring and owned tests as `feat: implement credential token lifecycle service`.

## Task 6: Expose User-Scoped Credential APIs

**Files:**

- Create: `backend/api/credentials.py`
- Modify: `backend/app.py` to register the blueprint and service extension.
- Test: `backend/tests/test_credentials_api.py`

**Interfaces:**

- `GET /api/credentials` lists only current user's non-deleted DTOs.
- `POST /api/credentials` accepts `label` and initial `token`; JSON body is limited to 64 KiB and rejects unknown fields. Response contains only safe DTO/result fields.
- `POST /api/credentials/<credential_id>/validate` accepts expected Credential version/current revision.
- `POST /api/credentials/<credential_id>/rotate-token` accepts candidate token and expected version/revision; only confirmed binding is eligible.
- `PATCH /api/credentials/<credential_id>` changes label or enabled state with expected version. `DELETE` soft-deletes with expected version.
- All mutation endpoints require the existing Session, allowed Origin/Referer, and CSRF checks. Cross-user IDs return same non-disclosing 404 as missing IDs. Upstream invalid Token is never returned as application 401; only explicit evidence-backed invalid mapping may use `422 credential_token_invalid`.
- Safe errors include `validation_rate_limited` with HTTP/JSON retry seconds, `validation_not_configured`, `validation_stale`, `credential_account_already_configured`, `credential_account_binding_unresolved`, `credential_account_reconfirmation_required`, `credential_token_expired`, and safe upstream contract/unknown errors. Never return upstream free-text.

- [ ] **Step 1: Write failing API tests**

  Cover login-required, CSRF/Origin rejection, schema body limits/unknown fields, all method/status mappings, exact DTO allowlist, invalid upstream code not clearing app Session, cross-user non-disclosing 404s, owner-scoped list/update/delete, no Token/fingerprint/raw profile in response, and unconfigured gate returning 503 without persistence.

- [ ] **Step 2: Run API tests and confirm expected failures**

  Run: `conda run -n test python -m unittest discover -s backend/tests -p 'test_credentials_api.py' -v`.

  Expected: new Credential route, ownership, CSRF, and safe-error assertions fail because the blueprint is not registered.

- [ ] **Step 3: Implement the Credential blueprint and factory wiring**

  Reuse `require_session`, `require_csrf`, and service-layer ownership predicates. Do not expose a route for key rotation, account fingerprint lookup, booking profile, or upstream raw responses.

- [ ] **Step 4: Run API tests**

  Run the same focused discover command from Step 2.

  Expected: fake upstream/gate tests pass, with no external requests.

- [ ] **Step 5: Commit the API layer**

  Commit the blueprint, app registration, and API tests as `feat: expose user-scoped credential APIs`.

## Task 7: Add the Credential Management UI

**Files:**

- Create: `frontend/src/api/credentials.js`
- Create: `frontend/src/views/CredentialView.vue`
- Create: `frontend/src/api/credentials.test.js`
- Create: `frontend/src/views/CredentialView.test.js`
- Modify: `frontend/src/router.js`
- Modify: `frontend/src/App.vue`
- Modify: `frontend/src/views/HomeView.vue`

**Interfaces:**

- Credential API helpers use the existing HTTP client, `credentials: include`, and in-memory CSRF behavior; no Token, CSRF, or account identifier enters browser storage, query parameters, router state, or logs.
- The view supports create, list, current Token validation, confirmed-only rotation, enable/disable, and soft delete. It clears Token fields after success, failure, cancel, or navigation.
- Display `account_binding_state` separately from expiry and Token validation. Show latest requested attempt with started/completed time and last successful validation separately. Explain `unresolved`/`needs_reconfirmation` restrictions; show only current-user same-account conflict guidance. Do not offer duplicate-confirmation controls.
- Home shows only current user's Credential expiry/binding warnings. `expiring_soon` is a reminder; `needs_reconfirmation` blocks account-bound future work. The view does not implement any booking or job controls.

- [ ] **Step 1: Install the checked-in frontend dependency lock**

  From `frontend/`, run `npm ci`. This new UI reuses the existing package manifest and lockfile; do not treat a missing Vitest binary as an expected red test.

- [ ] **Step 2: Write failing API helper and view tests**

  Cover initial list/create/validate/rotate/enable/disable/delete flows, busy/error/loading state, Token input clearing, unresolved/reconfirmation controls, latest-requested vs last-success display, same-account conflict behavior, and prohibition on Token/account-fingerprint placement in local/session storage or URLs.

- [ ] **Step 3: Run frontend tests and confirm expected failures**

  From `frontend/`, run `npm test -- --run`.

  Expected: existing identity UI tests pass; new Credential view/API assertions fail because the view and helper are not implemented.

- [ ] **Step 4: Implement route/navigation and Credential view**

  Add an authenticated `/credentials` route and visible navigation. Keep application auth error handling unchanged; upstream validation errors use non-401 result codes.

- [ ] **Step 5: Run frontend tests and production build**

  Run: `cd frontend && npm test -- --run`; then run `cd frontend && npm run build`.

  Expected: focused Credential tests and all existing frontend tests pass; build succeeds. Do not commit `frontend/dist/` or `frontend/node_modules/`.

- [ ] **Step 6: Commit the frontend**

  Commit only the named Vue/JS/test files as `feat: add credential management UI`.

## Task 8: Add Explicit Key Maintenance and Local Configuration Documentation

**Files:**

- Modify: `backend/cli.py`
- Create: `backend/credentials/maintenance.py`
- Modify: `docs/development/local-run.md`
- Test: `backend/tests/test_credential_maintenance.py`

**Interfaces:**

- Add `python -m backend.cli rewrap-credential-tokens` as an explicit CLI subcommand for ciphertext key rewrap. It runs in one database transaction, authenticates each active envelope before commit, appends safe lifecycle audit rows, and leaves semantic Token revision fields unchanged. It never logs or prints Token/key material.
- Startup/dependency scans are read-only. Key removal fails while active ciphertext, current Token fingerprint comparisons, or non-deleted confirmed/reconfirmation account fingerprints still depend on the key.
- Local-run instructions explain generation/injection of independent encryption/fingerprint keyrings, origin/timeouts/backoff settings, the evidence-backed interval, explicit `python -m backend.migrate`, and how missing interval leaves validation disabled. Documentation includes no real secret values.

- [ ] **Step 1: Write failing CLI/rewrap tests**

  Cover successful rewrap, wrong old key authentication failure, partial failure rollback, old-key dependency retention/removal rejection, historical inert key metadata, safe CLI output, and `AppSettings.__repr__`/logs not containing values.

- [ ] **Step 2: Run maintenance tests and confirm expected failures**

  Run: `conda run -n test python -m unittest discover -s backend/tests -p 'test_credential_maintenance.py' -v`.

  Expected: maintenance subcommand and safe rewrap assertions fail because the command is not implemented.

- [ ] **Step 3: Implement maintenance command and docs**

  Add only explicit administrative maintenance; do not expose key operations to Credential APIs. Document local env injection without printing secrets.

- [ ] **Step 4: Run maintenance tests and documentation checks**

  Run the same focused discover command from Step 2 and `git diff --check`.

  Expected: rewrap and dependency tests pass on temporary databases; documentation diff has no whitespace errors or real secrets.

- [ ] **Step 5: Commit maintenance and local docs**

  Commit the CLI, maintenance module, tests, and local-run documentation as `feat: add credential key maintenance`.

## Task 9: Full Acceptance and Git Integration

**Files:**

- Modify only if needed: the Task-owned files above; do not broaden scope.

**Interfaces:**

- Schema version 3 startup is read-only; explicit migrations are the only schema upgrade path.
- Local test commands are `conda run -n test python -m unittest discover -s backend/tests -v`, `cd frontend && npm test -- --run`, and `cd frontend && npm run build`.
- No real upstream requests are run. No raw `req/`, `.env`, DB, logs, Tokens, or generated frontend assets are committed.

- [ ] **Step 1: Review the full branch diff and changed-file allowlist**

  Confirm only the plan, evidence note, schema/config/service/API/UI/tests/local docs changed; verify `.env`, `req/`, DB/logs, `node_modules`, and `dist` are not staged or tracked.

- [ ] **Step 2: Run complete offline verification**

  Run all backend tests in Conda `test`, all Vitest tests, the production build, `git diff --check`, migration readiness/checksum tests, and secret-file status checks. Confirm no test contacted the real upstream.

- [ ] **Step 3: Review branch history and synchronize with `main`**

  Recheck whether local `main` advanced. If yes, rebase the feature branch and repeat all full verification. If not, retain the linear history.

- [ ] **Step 4: Merge and tag only after verification**

  From the primary checkout on `main`, merge with `git merge --ff-only feature/02-credential-token-lifecycle`. Verify the resulting `main` tree and tests, create tag `v1-credential-token-lifecycle` on that verified commit, then remove the feature branch/worktree. Preserve the primary checkout's unrelated untracked files throughout.

## Follow-On Plan Boundaries

This plan implements only Credential and Token lifecycle management. It does not implement Credential booking profiles, ReservationIntent/BookingPlan, BookingJob/Worker/ExecutionAttempt/locks, AvailabilityService, Preparation Agent, booking/price/order/payment calls, LLM Provider settings, or Tailscale deployment. No CAPTCHA automation or upstream rate-limit evasion is allowed.
