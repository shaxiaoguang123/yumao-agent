CREATE TABLE users (
    user_id TEXT PRIMARY KEY,
    username TEXT NOT NULL,
    normalized_username TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('admin', 'user')),
    status TEXT NOT NULL CHECK (status IN ('active', 'disabled')),
    created_at_utc_ms INTEGER NOT NULL,
    updated_at_utc_ms INTEGER NOT NULL,
    disabled_at_utc_ms INTEGER
);

CREATE TABLE sessions (
    session_id_hash TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(user_id) ON DELETE RESTRICT,
    created_at_utc_ms INTEGER NOT NULL,
    expires_at_utc_ms INTEGER NOT NULL,
    revoked_at_utc_ms INTEGER,
    csrf_scheme_version INTEGER NOT NULL DEFAULT 1
);

CREATE INDEX idx_sessions_user_id ON sessions(user_id);
CREATE INDEX idx_sessions_expiry ON sessions(expires_at_utc_ms);

CREATE TABLE invitations (
    invitation_code_hash TEXT PRIMARY KEY,
    created_by_user_id TEXT NOT NULL REFERENCES users(user_id) ON DELETE RESTRICT,
    created_at_utc_ms INTEGER NOT NULL,
    expires_at_utc_ms INTEGER NOT NULL,
    redeemed_at_utc_ms INTEGER,
    revoked_at_utc_ms INTEGER
);

CREATE INDEX idx_invitations_expiry ON invitations(expires_at_utc_ms);

CREATE TABLE auth_attempts (
    attempt_id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_type TEXT NOT NULL,
    bucket_type TEXT NOT NULL,
    bucket_key TEXT NOT NULL,
    attempted_at_utc_ms INTEGER NOT NULL
);

CREATE INDEX idx_auth_attempts_bucket_window
    ON auth_attempts(event_type, bucket_type, bucket_key, attempted_at_utc_ms);
