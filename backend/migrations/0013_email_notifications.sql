CREATE TABLE user_email_notification_settings (
    user_id TEXT PRIMARY KEY REFERENCES users(user_id) ON DELETE CASCADE,
    version INTEGER NOT NULL CHECK (version > 0),
    enabled INTEGER NOT NULL CHECK (enabled IN (0, 1)),
    reminder_time TEXT NOT NULL CHECK (length(reminder_time) = 5),
    last_test_sent_at_utc_ms INTEGER,
    updated_at_utc_ms INTEGER NOT NULL
);

CREATE TABLE booking_email_notification_outbox (
    notification_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    credential_id TEXT NOT NULL,
    target_date TEXT NOT NULL CHECK (length(target_date) = 10),
    kind TEXT NOT NULL CHECK (kind IN ('reminder', 'result')),
    queue_revision_id TEXT NOT NULL REFERENCES booking_plan_revisions(revision_id) ON DELETE RESTRICT,
    queue_version INTEGER NOT NULL CHECK (queue_version > 0),
    scheduled_at_utc_ms INTEGER NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('pending', 'sending', 'sent', 'failed', 'uncertain', 'cancelled')),
    attempt_count INTEGER NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
    next_attempt_at_utc_ms INTEGER NOT NULL,
    lease_owner_id TEXT,
    lease_expires_at_utc_ms INTEGER,
    provider_message_id TEXT,
    safe_error_code TEXT CHECK (safe_error_code IS NULL OR length(safe_error_code) <= 64),
    created_at_utc_ms INTEGER NOT NULL,
    updated_at_utc_ms INTEGER NOT NULL,
    sent_at_utc_ms INTEGER,
    UNIQUE (user_id, credential_id, target_date, kind),
    FOREIGN KEY (user_id, credential_id)
        REFERENCES credentials(user_id, credential_id) ON DELETE CASCADE,
    CHECK ((lease_owner_id IS NULL) = (lease_expires_at_utc_ms IS NULL))
);

CREATE INDEX booking_email_notification_due
    ON booking_email_notification_outbox(status, next_attempt_at_utc_ms, scheduled_at_utc_ms);

CREATE INDEX booking_email_notification_owner
    ON booking_email_notification_outbox(user_id, credential_id, target_date, kind);
