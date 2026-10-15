-- Per-credential schedules and durable, tenant-bound snapshots of executable queues.
CREATE TABLE booking_execution_settings (
    user_id TEXT NOT NULL,
    credential_id TEXT NOT NULL,
    version INTEGER NOT NULL CHECK (version > 0),
    reconciliation_time TEXT NOT NULL CHECK (length(reconciliation_time) = 5),
    clock_calibration_lead_ms INTEGER NOT NULL CHECK (clock_calibration_lead_ms BETWEEN 0 AND 30000),
    start_offset_ms INTEGER NOT NULL CHECK (start_offset_ms BETWEEN 0 AND 60000),
    booking_node_delay_ms INTEGER NOT NULL CHECK (booking_node_delay_ms BETWEEN 0 AND 60000),
    booking_by_time_delay_ms INTEGER NOT NULL CHECK (booking_by_time_delay_ms BETWEEN 0 AND 60000),
    get_user_info_delay_ms INTEGER NOT NULL CHECK (get_user_info_delay_ms BETWEEN 0 AND 60000),
    get_children_delay_ms INTEGER NOT NULL CHECK (get_children_delay_ms BETWEEN 0 AND 60000),
    get_pay_price_delay_ms INTEGER NOT NULL CHECK (get_pay_price_delay_ms BETWEEN 0 AND 60000),
    create_booking_delay_ms INTEGER NOT NULL CHECK (create_booking_delay_ms BETWEEN 0 AND 60000),
    open_platform_pay_order_delay_ms INTEGER NOT NULL CHECK (open_platform_pay_order_delay_ms BETWEEN 0 AND 60000),
    payment_verify_delay_ms INTEGER NOT NULL CHECK (payment_verify_delay_ms BETWEEN 0 AND 60000),
    updated_at_utc_ms INTEGER NOT NULL,
    PRIMARY KEY (user_id, credential_id),
    FOREIGN KEY (user_id, credential_id)
        REFERENCES credentials(user_id, credential_id) ON DELETE CASCADE
);

CREATE TABLE booking_execution_runs (
    run_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    credential_id TEXT NOT NULL,
    target_date TEXT NOT NULL,
    source_plan_id TEXT NOT NULL,
    source_revision_id TEXT NOT NULL,
    source_version INTEGER NOT NULL CHECK (source_version > 0),
    source_sha256 TEXT NOT NULL CHECK (length(source_sha256) = 64),
    state TEXT NOT NULL CHECK (state IN (
        'ready', 'calibrated', 'running', 'succeeded', 'failed', 'empty', 'stale', 'needs_attention'
    )),
    snapshot_json TEXT NOT NULL,
    reconciliation_json TEXT NOT NULL,
    clock_offset_ms INTEGER,
    clock_uncertainty_ms INTEGER,
    created_at_utc_ms INTEGER NOT NULL,
    updated_at_utc_ms INTEGER NOT NULL,
    started_at_utc_ms INTEGER,
    completed_at_utc_ms INTEGER,
    UNIQUE (user_id, credential_id, target_date, source_revision_id),
    FOREIGN KEY (source_revision_id, source_plan_id, user_id, source_version)
        REFERENCES booking_plan_revisions(revision_id, plan_id, user_id, revision_number)
        ON DELETE RESTRICT,
    FOREIGN KEY (user_id, credential_id)
        REFERENCES credentials(user_id, credential_id) ON DELETE CASCADE
);
CREATE INDEX booking_execution_runs_due
    ON booking_execution_runs(state, target_date, updated_at_utc_ms);

CREATE TABLE booking_execution_stages (
    stage_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES booking_execution_runs(run_id) ON DELETE CASCADE,
    round_number INTEGER NOT NULL CHECK (round_number >= 0),
    candidate_index INTEGER NOT NULL CHECK (candidate_index >= 0),
    stage_key TEXT NOT NULL,
    started_at_utc_ms INTEGER NOT NULL,
    completed_at_utc_ms INTEGER NOT NULL,
    elapsed_ms INTEGER NOT NULL CHECK (elapsed_ms >= 0),
    outcome TEXT NOT NULL CHECK (outcome IN ('success', 'rejected', 'failed', 'uncertain', 'skipped')),
    safe_code TEXT,
    UNIQUE (run_id, round_number, candidate_index, stage_key)
);
CREATE INDEX booking_execution_stages_by_run
    ON booking_execution_stages(run_id, round_number, candidate_index, started_at_utc_ms);

CREATE TRIGGER booking_execution_runs_owner_immutable
BEFORE UPDATE ON booking_execution_runs
WHEN NEW.run_id IS NOT OLD.run_id OR NEW.user_id IS NOT OLD.user_id
    OR NEW.credential_id IS NOT OLD.credential_id OR NEW.target_date IS NOT OLD.target_date
    OR NEW.source_plan_id IS NOT OLD.source_plan_id
    OR NEW.source_revision_id IS NOT OLD.source_revision_id
    OR NEW.source_version IS NOT OLD.source_version OR NEW.source_sha256 IS NOT OLD.source_sha256
    OR NEW.snapshot_json IS NOT OLD.snapshot_json OR NEW.reconciliation_json IS NOT OLD.reconciliation_json
    OR NEW.created_at_utc_ms IS NOT OLD.created_at_utc_ms
BEGIN
    SELECT RAISE(ABORT, 'booking execution snapshot is immutable');
END;
