-- Manual drafts share the plan/revision boundary with future explicit catalog binding.
CREATE TABLE booking_plans (
    plan_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(user_id),
    current_revision_id TEXT NOT NULL,
    version INTEGER NOT NULL CHECK (version > 0),
    created_at_utc_ms INTEGER NOT NULL,
    updated_at_utc_ms INTEGER NOT NULL,
    UNIQUE (plan_id, user_id),
    FOREIGN KEY (current_revision_id, plan_id, user_id, version)
        REFERENCES booking_plan_revisions(revision_id, plan_id, user_id, revision_number)
        DEFERRABLE INITIALLY DEFERRED
);

CREATE TABLE booking_plan_revisions (
    revision_id TEXT PRIMARY KEY,
    plan_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    revision_number INTEGER NOT NULL CHECK (revision_number > 0),
    intent_json TEXT NOT NULL,
    intent_sha256 TEXT NOT NULL CHECK (length(intent_sha256) = 64),
    created_by_user_id TEXT NOT NULL CHECK (created_by_user_id = user_id),
    created_at_utc_ms INTEGER NOT NULL,
    UNIQUE (revision_id, plan_id, user_id, revision_number),
    UNIQUE (plan_id, user_id, revision_number),
    FOREIGN KEY (plan_id, user_id) REFERENCES booking_plans(plan_id, user_id),
    FOREIGN KEY (created_by_user_id) REFERENCES users(user_id)
);

CREATE INDEX booking_plans_by_user ON booking_plans(user_id, updated_at_utc_ms DESC, plan_id);

CREATE TRIGGER booking_plan_revisions_no_update
BEFORE UPDATE ON booking_plan_revisions BEGIN
    SELECT RAISE(ABORT, 'plan revisions are immutable');
END;

CREATE TRIGGER booking_plan_revisions_no_delete
BEFORE DELETE ON booking_plan_revisions BEGIN
    SELECT RAISE(ABORT, 'plan revisions are immutable');
END;

CREATE TRIGGER booking_plans_advance_only
BEFORE UPDATE ON booking_plans
WHEN NEW.plan_id IS NOT OLD.plan_id OR NEW.user_id IS NOT OLD.user_id
    OR NEW.created_at_utc_ms IS NOT OLD.created_at_utc_ms OR NEW.version != OLD.version + 1
BEGIN
    SELECT RAISE(ABORT, 'plan ownership is immutable and versions advance by one');
END;
