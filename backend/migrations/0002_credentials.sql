CREATE TABLE credentials (
    credential_id TEXT NOT NULL PRIMARY KEY,
    user_id TEXT NOT NULL,
    label TEXT NOT NULL CHECK (length(label) BETWEEN 1 AND 128),
    credential_version INTEGER NOT NULL CHECK (credential_version > 0),
    enabled INTEGER NOT NULL CHECK (enabled IN (0, 1)),
    deleted_at_utc_ms INTEGER,
    current_token_revision_id TEXT NOT NULL,
    account_binding_state TEXT NOT NULL
        CHECK (account_binding_state IN ('unresolved', 'confirmed', 'needs_reconfirmation')),
    upstream_account_fingerprint TEXT,
    fingerprint_key_version TEXT,
    account_identity_contract_version TEXT,
    account_fingerprint_cleared_at_utc_ms INTEGER,
    last_successful_validation_at_utc_ms INTEGER,
    last_confirmed_validation_state TEXT NOT NULL
        CHECK (last_confirmed_validation_state IN ('never_confirmed', 'confirmed_valid', 'confirmed_invalid')),
    requires_revalidation INTEGER NOT NULL CHECK (requires_revalidation IN (0, 1)),
    created_at_utc_ms INTEGER NOT NULL,
    updated_at_utc_ms INTEGER NOT NULL,
    UNIQUE (user_id, credential_id),
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE RESTRICT,
    FOREIGN KEY (user_id, credential_id, current_token_revision_id)
        REFERENCES credential_token_revisions(user_id, credential_id, revision_id)
        DEFERRABLE INITIALLY DEFERRED,
    CHECK (
        (account_binding_state = 'unresolved'
         AND upstream_account_fingerprint IS NULL
         AND fingerprint_key_version IS NULL
         AND account_identity_contract_version IS NULL)
        OR
        (account_binding_state IN ('confirmed', 'needs_reconfirmation')
         AND upstream_account_fingerprint IS NOT NULL
         AND fingerprint_key_version IS NOT NULL
         AND account_identity_contract_version IS NOT NULL)
    )
);

CREATE TABLE credential_token_revisions (
    revision_id TEXT NOT NULL PRIMARY KEY,
    user_id TEXT NOT NULL,
    credential_id TEXT NOT NULL,
    revision_number INTEGER NOT NULL CHECK (revision_number > 0),
    token_fingerprint TEXT NOT NULL CHECK (length(token_fingerprint) = 64),
    token_fingerprint_key_version TEXT NOT NULL,
    token_expires_at_utc_ms INTEGER,
    initial_account_fingerprint_key_version TEXT,
    initial_account_identity_contract_version TEXT,
    initial_validation_result TEXT NOT NULL CHECK (initial_validation_result = 'success'),
    initial_validation_at_utc_ms INTEGER NOT NULL,
    created_by_user_id TEXT NOT NULL,
    secret_material_active INTEGER NOT NULL CHECK (secret_material_active IN (0, 1)),
    ciphertext BLOB,
    nonce BLOB,
    tag BLOB,
    encryption_key_version TEXT NOT NULL,
    ciphertext_cleared_at_utc_ms INTEGER,
    UNIQUE (user_id, credential_id, revision_number),
    UNIQUE (user_id, credential_id, revision_id),
    FOREIGN KEY (user_id, credential_id)
        REFERENCES credentials(user_id, credential_id) ON DELETE RESTRICT,
    FOREIGN KEY (created_by_user_id) REFERENCES users(user_id) ON DELETE RESTRICT,
    CHECK (
        (initial_account_fingerprint_key_version IS NULL
         AND initial_account_identity_contract_version IS NULL)
        OR
        (initial_account_fingerprint_key_version IS NOT NULL
         AND initial_account_identity_contract_version IS NOT NULL)
    ),
    CHECK (
        (secret_material_active = 1
         AND ciphertext IS NOT NULL
         AND nonce IS NOT NULL AND length(nonce) = 12
         AND tag IS NOT NULL AND length(tag) = 16
         AND ciphertext_cleared_at_utc_ms IS NULL)
        OR
        (secret_material_active = 0
         AND ciphertext IS NULL AND nonce IS NULL AND tag IS NULL
         AND ciphertext_cleared_at_utc_ms IS NOT NULL)
    )
);

CREATE TABLE credential_validation_observations (
    validation_attempt_id INTEGER PRIMARY KEY,
    user_id TEXT NOT NULL,
    credential_id TEXT,
    operation_kind TEXT NOT NULL
        CHECK (operation_kind IN ('create_candidate', 'validate_current', 'token_rotation_candidate')),
    credential_version_snapshot INTEGER,
    current_token_revision_snapshot_id TEXT,
    token_revision_id TEXT,
    started_at_utc_ms INTEGER NOT NULL,
    completed_at_utc_ms INTEGER NOT NULL,
    attempt_result TEXT NOT NULL CHECK (attempt_result IN (
        'success', 'explicit_invalid', 'network_error', 'rate_limited',
        'contract_drift', 'validation_unknown', 'unresolved_identity', 'internal_error'
    )),
    account_binding_outcome TEXT CHECK (account_binding_outcome IN (
        'not_checked', 'unresolved', 'confirmed', 'mismatch', 'duplicate_conflict'
    )),
    http_status_class TEXT CHECK (http_status_class IN ('1xx', '2xx', '3xx', '4xx', '5xx')),
    gate_owner_id TEXT,
    gate_epoch INTEGER,
    apply_state TEXT NOT NULL CHECK (apply_state IN (
        'applied', 'candidate_rejected', 'not_dispatched', 'stale'
    )),
    FOREIGN KEY (user_id, credential_id)
        REFERENCES credentials(user_id, credential_id) ON DELETE RESTRICT,
    FOREIGN KEY (user_id, credential_id, token_revision_id)
        REFERENCES credential_token_revisions(user_id, credential_id, revision_id)
        ON DELETE RESTRICT
);

CREATE INDEX idx_credential_validation_user_credential_attempt
    ON credential_validation_observations(user_id, credential_id, validation_attempt_id DESC);

CREATE TABLE credential_lifecycle_audits (
    audit_id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    credential_id TEXT NOT NULL,
    revision_id TEXT,
    actor_user_id TEXT NOT NULL,
    operation_code TEXT NOT NULL CHECK (operation_code IN (
        'key_rewrapped', 'fingerprint_rebound', 'binding_confirmed',
        'binding_needs_reconfirmation', 'binding_reconfirmed',
        'enabled', 'disabled', 'soft_deleted', 'ciphertext_cleared'
    )),
    old_key_version TEXT,
    new_key_version TEXT,
    old_identity_contract_version TEXT,
    new_identity_contract_version TEXT,
    occurred_at_utc_ms INTEGER NOT NULL,
    outcome TEXT NOT NULL CHECK (outcome IN ('success', 'failure')),
    FOREIGN KEY (user_id, credential_id)
        REFERENCES credentials(user_id, credential_id) ON DELETE RESTRICT,
    FOREIGN KEY (user_id, credential_id, revision_id)
        REFERENCES credential_token_revisions(user_id, credential_id, revision_id)
        ON DELETE RESTRICT,
    FOREIGN KEY (actor_user_id) REFERENCES users(user_id) ON DELETE RESTRICT
);

CREATE INDEX idx_credential_lifecycle_user_credential_audit
    ON credential_lifecycle_audits(user_id, credential_id, audit_id DESC);

CREATE TABLE upstream_request_gate (
    endpoint_key TEXT NOT NULL PRIMARY KEY CHECK (endpoint_key = 'getUserInfo'),
    lease_owner_id TEXT,
    lease_epoch INTEGER NOT NULL DEFAULT 0 CHECK (lease_epoch >= 0),
    lease_expires_at_utc_ms INTEGER,
    next_validation_attempt_id INTEGER NOT NULL DEFAULT 1 CHECK (next_validation_attempt_id > 0),
    active_validation_attempt_id INTEGER,
    active_user_id TEXT,
    active_credential_id TEXT,
    active_operation_kind TEXT,
    active_credential_version_snapshot INTEGER,
    active_token_revision_snapshot_id TEXT,
    next_allowed_at_utc_ms INTEGER,
    upstream_backoff_until_utc_ms INTEGER,
    FOREIGN KEY (active_user_id, active_credential_id)
        REFERENCES credentials(user_id, credential_id) ON DELETE RESTRICT,
    CHECK (
        (lease_owner_id IS NULL
         AND lease_expires_at_utc_ms IS NULL
         AND active_validation_attempt_id IS NULL
         AND active_user_id IS NULL
         AND active_credential_id IS NULL
         AND active_operation_kind IS NULL)
        OR
        (lease_owner_id IS NOT NULL
         AND lease_expires_at_utc_ms IS NOT NULL
         AND active_validation_attempt_id IS NOT NULL
         AND active_user_id IS NOT NULL
         AND active_operation_kind IS NOT NULL)
    )
);

INSERT INTO upstream_request_gate (endpoint_key) VALUES ('getUserInfo');

CREATE TRIGGER credential_validation_observations_no_update
BEFORE UPDATE ON credential_validation_observations
BEGIN
    SELECT RAISE(ABORT, 'credential validation observations are append-only');
END;

CREATE TRIGGER credential_validation_observations_no_delete
BEFORE DELETE ON credential_validation_observations
BEGIN
    SELECT RAISE(ABORT, 'credential validation observations are append-only');
END;

CREATE TRIGGER credential_lifecycle_audits_no_update
BEFORE UPDATE ON credential_lifecycle_audits
BEGIN
    SELECT RAISE(ABORT, 'credential lifecycle audits are append-only');
END;

CREATE TRIGGER credential_lifecycle_audits_no_delete
BEFORE DELETE ON credential_lifecycle_audits
BEGIN
    SELECT RAISE(ABORT, 'credential lifecycle audits are append-only');
END;
