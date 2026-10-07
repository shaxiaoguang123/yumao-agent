# V1 Credential and Token Lifecycle Design

- Date: 2026-10-07
- Status: Design draft / awaiting user review
- Parent architecture: [V1 Final Architecture Spec](2026-10-07-multiuser-booking-design.md)
- Predecessor milestone: V1 Identity and App Foundation, tag `v1-identity-foundation`

## 1. Purpose

Define the next independently reviewable subsystem after identity foundation: user-owned upstream Credentials and their Token lifecycle. A user must be able to add, validate, rotate, inspect safe expiry metadata for, disable, and soft-delete a Credential without exposing its Token or upstream personal data.

This design retains Flask + Vue + SQLite, server-side Sessions, strict `user_id` isolation, and the existing local-first development model. It adds no service, queue, or database server.

## 2. Scope

### Included

- Credential and append-only CredentialTokenRevision persistence and migration from schema version 1.
- Application-level authenticated encryption for Token revisions, with versioned keys and authenticated context.
- Local parsing of JWT `exp` as a reminder only; a req-confirmed read-only upstream check remains the evidence of current validity.
- Same-account Token rotation, opaque account fingerprints, safe status reporting, user-scoped APIs, and Vue management UI.
- A persistent, service-wide UpstreamRequestGate for the read-only validation call. The gate is shared across all users and Credentials and honors configured spacing and upstream `Retry-After` evidence.
- Synthetic, sanitized contract fixtures and temporary-database tests.

### Excluded

- Credential booking profiles or participant-data entry. These require a separate reviewed design because they contain personal information and are not needed to validate a Token.
- ReservationIntent, BookingPlan, BookingJob, Worker execution, execution locks, booking availability, booking/payment calls, Agent tools, LLM Provider configuration, and Tailscale deployment.
- Automatic Token refresh or upstream Token revocation.

## 3. Upstream Evidence and Contract Boundary

The local `req/` capture set contains a `POST` request to:

`/service/appointment/appointment/userAddress/getUserInfo`

The captured successful response envelope is `success`, `message`, and `resultData`; the observed success samples have `success=true` and `message=CORE10008`. The observed `resultData` contains `idserial`, `tel`, and `username`. The official frontend calls its `getUserInfo()` method during page loading and uses `user.idserial` as `reservationPerson` in the later booking request. These observations establish that the response contains personal data and that `idserial` participates in the upstream booking identity. The four observed `getUserInfo` samples are successful; they do not establish the invalid-Token response mapping. The contract task must verify both that `idserial` is stable and unique enough to bind Credential rotations and which exact responses prove invalid authentication.

The validation adapter accepts only the exact response shape and endpoint-specific success/error combinations established from `req/` and the official frontend. HTTP 200 alone is not success. Missing/changed fields, unknown message codes, ambiguous authentication failures, or unreadable identity values fail closed. Until an explicit invalid-Token response is evidenced, non-success responses remain `validation_unknown`/contract failure and cannot set `invalid`. No endpoint other than the confirmed read-only `getUserInfo` flow is used to validate a Token in this phase.

Before implementation, the plan must verify that the observed `idserial` is stable enough to identify the same upstream account across Token replacement. If that semantic cannot be established from the captures and official frontend, Token replacement must remain blocked when account continuity cannot be proved. The implementation must not fall back to a display name, telephone number, fuzzy match, or a guessed identifier.

`getUserInfo` returns personal fields. The adapter processes the response in memory, extracts only the confirmed identity field needed for account continuity, computes its keyed fingerprint, and discards the response. It must not persist or return `idserial`, telephone number, username, raw JSON, request/response bodies, or a copy of the decrypted response.

The capture data and official frontend remain local analysis sources. Raw req files, real Tokens, personal data, decrypted payloads, and real request/response bodies must never enter Git, fixtures, logs, API responses, or Agent context.

## 4. Components and Data Flow

1. **Credential API and service** authenticate the current Session, bind every query to its `user_id`, validate input, and coordinate validation and revision changes.
2. **CredentialTokenService** parses only the JWT `exp` claim, delegates read-only validation, computes account/token fingerprints, and enforces rotation rules.
3. **SecretEncryptionService** encrypts and decrypts Token ciphertext with an established authenticated-encryption implementation. It never reads upstream protocol keys as application storage keys.
4. **UpstreamContractAdapter** exposes only the validated `getUserInfo` operation in this phase. All upstream access goes through the shared **UpstreamRequestGate**.
5. **SQLite** stores user-owned Credentials, immutable Token revision metadata, ciphertext, and the gate's shared scheduling state. No in-memory queue is an authority.
6. **Vue Credential views** submit the Token once, then show safe status and expiry metadata. The browser does not persist the Token or account fingerprint.

The validation request is initiated only when a user adds a Token, rotates it, or explicitly asks to validate it. This phase does not add a background Worker. Any future preflight flow reuses the same adapter and request gate rather than creating a second validation path.

## 5. Entities and Persistence

### Credential

The Credential row contains:

- `credential_id`, `user_id`, and user-provided display `label`.
- `current_token_revision_id`, current enabled/disabled state, creation/update times, and `deleted_at_utc_ms` for soft deletion.
- A versioned `upstream_account_fingerprint` and fingerprint-key version. This is an internal keyed value and is never returned to users or Agents.
- Safe current validation summary and `last_validated_at_utc_ms`.

The current expiry status is derived from the current Token revision and its latest validation result, so the API does not combine unrelated Credentials or Job risks into a global status. The future `will_expire_before_job` value is a Credential+Job projection and is not implemented before BookingJob exists.

### CredentialTokenRevision

Each rotation appends a revision with:

- `revision_id`, `user_id`, `credential_id`, monotonic revision number, creation time, and actor.
- Authenticated ciphertext, nonce/tag representation, and encryption-key version.
- A keyed, non-reversible Token fingerprint for duplicate detection/audit; never the Token or a plain JWT payload hash.
- `token_expires_at_utc_ms` when a valid numeric `exp` can be decoded; otherwise `NULL` and `unknown` expiry status.
- Safe validation status and validation time, plus explicit Token-fingerprint and account-fingerprint key-version IDs.
- Ciphertext-destruction time when the revision is no longer allowed to be used.

The semantic Token revision is immutable. Cryptographic key rotation may rewrap its encrypted envelope in place only inside a transaction and must append a safe key-rewrap audit event; it cannot change the Token fingerprint, expiry claim, account binding, actor, or creation time.

Composite uniqueness and foreign keys bind every revision and current pointer to the same owning `user_id` and Credential. API SQL always scopes by the authenticated `user_id`; it never loads by `credential_id` alone and checks ownership later in Python.

The existing migration `0001_identity.sql` remains immutable. Credential tables and the shared request gate use a new numbered migration, initially `0002_credentials.sql`, applied only by the explicit migration command. Flask startup remains read-only and fails fast on an unready schema.

## 6. Secret and Fingerprint Protection

### Token encryption

- Use AES-256-GCM through the project's existing `pycryptodome` dependency, with a fresh 96-bit nonce and 128-bit authentication tag for each encryption. Do not add another crypto service or custom cipher.
- Bind ciphertext to `user_id`, `credential_id`, `revision_id`, and key version using authenticated additional data. Moving ciphertext between rows or owners must fail authentication.
- Load an explicit versioned application keyring from protected environment/secret-manager configuration, conceptually `APP_CREDENTIAL_ENCRYPTION_KEYS` plus `APP_CREDENTIAL_ENCRYPTION_ACTIVE_KEY_ID`. The keyring maps key-version IDs to canonical base64url-encoded 32-byte keys, and the active key ID is explicit. Decryption may use retained older key versions during rotation. Missing keys, malformed encodings, or unavailable key versions fail fast before accepting Token writes.
- Keep the application encryption key separate from upstream AES request-encryption material, `CSRF_HMAC_SECRET`, database contents, and account-fingerprint HMAC keys. Never put any secret in SQLite, Git, logs, or `AppSettings.__repr__`.
- Application key rotation re-encrypts all retained ciphertext under the new key version transactionally, verifies authentication before commit, and retains old decryption keys until the migration is complete. A partial re-encryption rolls back; it never silently changes key IDs without successfully changing ciphertext.

### Account and Token fingerprints

- Load a separate versioned HMAC keyring from protected configuration, conceptually `APP_UPSTREAM_FINGERPRINT_KEYS` plus `APP_UPSTREAM_FINGERPRINT_ACTIVE_KEY_ID`. Derive the account fingerprint with HMAC-SHA-256 over a canonical encoding of the confirmed upstream identity field plus the `upstream-account-v1` domain separator. Do not use an unkeyed hash of `idserial`.
- HMAC keyring values are independent 32-byte CSPRNG secrets with strict canonical base64url decoding; their settings are excluded from repr and logs. The confirmed identity field is encoded exactly as returned with an unambiguous length prefix; do not trim, casefold, parse as an integer, or otherwise normalize an identity value without explicit contract evidence.
- Derive Token fingerprints with a distinct `credential-token-v1` domain separator so the account fingerprint cannot be used to compare Tokens and vice versa.
- Store only the keyed fingerprint and key version. Do not expose the value, use it as a UI identifier, or log it.
- Keep old HMAC key versions available while Credentials still reference them. For duplicate detection or rotation, compute candidate HMACs under retained key versions and compare only matching versions. Migration to a new version revalidates each Credential and atomically updates its fingerprint; if continuity cannot be established, keep the old key version and fail closed. A later account-lock phase must rekey all lock identities atomically before retiring any referenced fingerprint key.

## 7. Token State and Validation Rules

Credential status and Token validity are distinct:

- `active`: user may explicitly validate or rotate the current Token.
- `disabled`: no upstream calls are allowed until the user re-enables and validates it.
- `deleted`: hidden from normal listing and barred from new use; soft deletion is not upstream Token revocation.

The current Token expiry/validation state is one of:

- `valid`: latest read-only validation succeeded and `exp` is beyond the configured reminder window.
- `expiring_soon`: latest validation succeeded and `exp` is within the configured reminder window, defaulting to 7 days as set in the parent architecture. This is a UI warning, not a block by itself.
- `expired`: decoded `exp` is at or before current UTC time. No upstream call is allowed.
- `invalid`: the confirmed read-only endpoint returned an explicit, contract-verified invalid/unauthorized Token result. No upstream call is allowed until rotation and successful validation.
- `unknown`: `exp` is absent/unparseable or validity has not been confirmed. Local JWT parsing never verifies a signature. Before a future business request, a successful contract-verified read-only validation is required; if `exp` remains unavailable, keep showing `unknown`.

`will_expire_before_job` is calculated later per Credential+Job from that Job's current resolved execution time. It must not be stored as a global Credential state. If a submitted Token has a parseable `exp` at or before the current UTC time, reject it before the validation call. An expired/invalid Credential cannot be used to query `getUserInfo`, booking availability, prices, orders, or write endpoints; an explicit user-submitted replacement is the only path to recovery.

## 8. Operations and API Semantics

All mutation routes require a valid server Session, Origin/Referer validation, and the existing session-bound CSRF token.

- `GET /api/credentials` lists only the current user's non-deleted Credentials and safe metadata. It omits Token values, raw profile data, Token fingerprints, and account fingerprints.
- `POST /api/credentials` accepts a display label and one Token value in the JSON body. The API validates the Token through the shared gate and confirmed read-only adapter before creating the Credential and first Token revision. The response contains only the new ID, label, safe validation result, expiry time/status, and validation timestamp. It never returns the submitted Token.
- `POST /api/credentials/{credential_id}/validate` revalidates the current revision after checking ownership and enabled state. It returns only a safe status code and timestamp. `expired` and explicitly `invalid` current revisions are blocked locally and require Token rotation; `unknown`, `valid`, and `expiring_soon` revisions may use the shared read-only validation call. Network timeout, 429, unknown response, or contract drift is not reported as a confirmed invalid Token.
- `POST /api/credentials/{credential_id}/token-rotation` accepts the new Token and the expected current revision identifier. It validates the candidate before opening the revision transaction, then checks the expected current revision and account fingerprint under a write transaction. A stale revision returns 409. A different or unresolved account identity returns a safe conflict and leaves the prior revision current. A matching account creates an immutable new revision and atomically advances the current pointer.
- `PATCH /api/credentials/{credential_id}` may change the safe display label or enable/disable the Credential, with an optimistic version check. It cannot change Token, fingerprint, expiry, or payment fields.
- `DELETE /api/credentials/{credential_id}` soft-deletes the owned Credential and immediately disables new calls. In this phase no Job/attempt can reference a revision, so encrypted Token material is destroyed and only a no-secret tombstone remains. A later Job plan must add explicit revision references and preserve ciphertext only for active attempts or unresolved side effects.

Creating another Credential for an account already represented among the same user's active Credentials returns a safe conflict and recommends rotating the existing Credential. Cross-user account matches are never disclosed. Future account-level execution locks must use the same fingerprint without exposing it.

Validation failure categories are allow-listed: explicit invalid Token, transient network failure, upstream rate limited, contract drift, unresolved account identity, account mismatch, and internal validation error. Responses never include raw upstream `message`, JSON, headers, URL query, or stack trace.

## 9. Shared Request Gate and Failure Behavior

Every `getUserInfo` call passes through one SQLite-backed `UpstreamRequestGate` shared across users and Credentials. It serializes in-flight requests to the same endpoint, enforces an evidence-based configured minimum interval, stores cross-Credential `Retry-After`/backoff, and returns a safe retry delay. There is no per-user, per-Credential, or per-Agent gate that could be combined to evade upstream limits.

The gate claims a short-lived endpoint lease and checks `next_allowed_at_utc_ms` inside `BEGIN IMMEDIATE`; the lease expiry exceeds the configured HTTP connect/read timeout. Completion or timeout releases the lease and updates the next permitted time/backoff atomically. After a process crash, an expired lease can be reclaimed; the read-only call may be repeated only after the gate permits it.

The parent architecture records an observed successful same-endpoint interval of approximately 668 ms with no observed 429/Retry-After response, but it does not identify that endpoint as `getUserInfo`. Do not apply 668 ms to this endpoint unless the evidence task proves the match. `getUserInfo` validation stays disabled until an endpoint-scoped minimum interval is set from req timing evidence, a documented successful run, or an upstream response. While disabled, add/rotate/validate requests return safe `validation_not_configured` and persist no submitted Token. The gate is not the UI refresh policy; it serializes in-flight requests, enforces the configured minimum, and applies any upstream `Retry-After` as a stronger cross-Credential backoff. Explicit user validation may not bypass the shared gate.

Failure rules:

- Validation occurs before new Credential/Token revision becomes current. Any timeout, 429, upstream 5xx, malformed response, contract drift, or unresolved identity leaves the old current revision unchanged.
- Only a confirmed endpoint-specific invalid/unauthorized response marks a Token `invalid`; a generic failure never does.
- If account continuity cannot be proven, do not replace the current Token or guess by username/telephone similarity.
- If encryption/decryption fails, do not call upstream or return ciphertext details; fail closed with a generic configuration error and a safe operator diagnostic code.
- Because this phase has no write side effects, a read-only validation timeout can be retried by explicit user action after gate/backoff. The implementation must not use extra Tokens to bypass the gate.

## 10. UI and Privacy

The Credential page shows label, enabled state, expiry date/status, last successful validation time, and safe result text. It includes add, validate, same-account rotate, enable/disable, and soft-delete actions. The logged-in home shell summarizes the user's own expired/invalid/expiring/unknown Token risks and links to Credential management.

Token input exists only in the form's memory and one API request body. Clear it after success, failure, or cancellation. Local development uses the loopback API transport; a deployed instance must use HTTPS. Never put the Token in a URL, router state, local/session storage, analytics, frontend error message, or browser log. Do not return it in API responses. The UI never displays the account fingerprint or upstream `idserial`, telephone number, or username learned during validation.

Logs use field allow-lists. They may include credential ID, revision number, endpoint identifier, HTTP status class, safe validation code, duration bucket, and request-gate outcome. They must omit Token, JWT/payload, authorization headers, raw request/response, `idserial`, phone, username, fingerprint, and URL query parameters.

## 11. Acceptance Criteria

- A new migration adds Credential, Token revision, and request-gate tables with foreign keys, unique revision ordering, user ownership constraints, and required indexes. Existing identity data remains intact; schema readiness and checksum behavior continue to work.
- A user can create a Credential with a valid synthetic Token-validation fixture; only ciphertext and safe metadata persist. Database, API, logs, frontend state, and test reports contain no raw Token or personal profile values.
- `exp` parsing stores only an integer UTC expiry and state; malformed/missing `exp` becomes `unknown` and never claims the Token is valid without read-only validation.
- The `getUserInfo` adapter verifies HTTP status plus endpoint-specific JSON success/message/resultData contract. Unknown field/type/message changes fail closed as contract drift.
- Missing/ambiguous `idserial` semantics or value fails account assignment/rotation closed. Once its identity meaning is verified, only a dedicated HMAC fingerprint is persisted; the original identity field is discarded.
- Rotation against the same account appends a revision and atomically advances the pointer. A different-account or unknown-account Token cannot overwrite the current revision. A stale expected revision returns 409.
- A Token explicitly invalidated by the upstream read-only check is blocked; transient network/429/5xx and contract drift remain distinguishable from invalid credentials.
- Same-user duplicate Credential creation is clearly rejected without exposing the fingerprint; cross-user data and existence are never disclosed.
- Disabling/deleting a Credential blocks further calls. Soft delete clears revision ciphertext when there are no future execution references and retains only safe audit metadata.
- Every call is subject to the persistent shared request gate across users/Credentials and honors upstream `Retry-After`. Tests verify multiple Credentials cannot acquire independent permits.
- API resources, list/update/rotation/deletion queries, and validation actions are bound to the current `user_id`; cross-user credential IDs return the same non-disclosing 404 as a missing Credential.
- Tests use temporary SQLite and synthetic fixtures only. They do not load `.env`, read raw req files, print secrets, or call real upstream services.
- Tailscale, BookingPlan, BookingJob, Worker, Agent, payment, and booking UI routes are not added in this phase.

## 12. Handoff to Implementation Planning

After this design is approved, the separate implementation plan should preserve Task-sized, test-first commits on a short-lived feature branch/worktree based on `main`, with final rebase, full backend/frontend/build acceptance, fast-forward merge, cleanup, and a milestone tag. The plan must include an initial evidence task to establish the stable identity meaning of `idserial`, confirm exact `getUserInfo` response classification, and set request-gate defaults from evidence before any live validation path is enabled.

Approval of this design permits drafting that implementation plan only. It does not authorize beginning Credential code, live upstream validation, BookingJob work, or deployment.
