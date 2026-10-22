-- One timing profile per user. Every enabled credential owned by that user
-- snapshots the same profile when its D+2 queue is reconciled.
CREATE TABLE user_booking_execution_settings (
    user_id TEXT PRIMARY KEY REFERENCES users(user_id) ON DELETE CASCADE,
    version INTEGER NOT NULL CHECK (version > 0),
    reconciliation_time TEXT NOT NULL CHECK (length(reconciliation_time) = 5),
    clock_calibration_lead_ms INTEGER NOT NULL CHECK (clock_calibration_lead_ms BETWEEN 0 AND 30000),
    start_offset_ms INTEGER NOT NULL CHECK (start_offset_ms BETWEEN 0 AND 60000),
    booking_node_delay_ms INTEGER NOT NULL CHECK (booking_node_delay_ms BETWEEN 0 AND 60000),
    booking_by_time_delay_ms INTEGER NOT NULL CHECK (booking_by_time_delay_ms BETWEEN 0 AND 60000),
    get_user_info_delay_ms INTEGER NOT NULL CHECK (get_user_info_delay_ms BETWEEN 0 AND 60000),
    get_pay_price_delay_ms INTEGER NOT NULL CHECK (get_pay_price_delay_ms BETWEEN 0 AND 60000),
    create_booking_delay_ms INTEGER NOT NULL CHECK (create_booking_delay_ms BETWEEN 0 AND 60000),
    open_platform_pay_order_delay_ms INTEGER NOT NULL CHECK (open_platform_pay_order_delay_ms BETWEEN 0 AND 120000),
    payment_verify_delay_ms INTEGER NOT NULL CHECK (payment_verify_delay_ms BETWEEN 0 AND 60000),
    payment_verify_interval_ms INTEGER NOT NULL CHECK (payment_verify_interval_ms BETWEEN 0 AND 60000),
    candidate_interval_ms INTEGER NOT NULL CHECK (candidate_interval_ms BETWEEN 0 AND 60000),
    updated_at_utc_ms INTEGER NOT NULL
);

-- Preserve the most recently updated legacy per-credential profile for each user.
INSERT INTO user_booking_execution_settings (
    user_id, version, reconciliation_time, clock_calibration_lead_ms, start_offset_ms,
    booking_node_delay_ms, booking_by_time_delay_ms, get_user_info_delay_ms,
    get_pay_price_delay_ms, create_booking_delay_ms, open_platform_pay_order_delay_ms,
    payment_verify_delay_ms, payment_verify_interval_ms, candidate_interval_ms,
    updated_at_utc_ms
)
SELECT
    legacy.user_id, legacy.version, legacy.reconciliation_time,
    legacy.clock_calibration_lead_ms, legacy.start_offset_ms,
    legacy.booking_node_delay_ms, legacy.booking_by_time_delay_ms,
    legacy.get_user_info_delay_ms, legacy.get_pay_price_delay_ms,
    legacy.create_booking_delay_ms, legacy.open_platform_pay_order_delay_ms,
    legacy.payment_verify_delay_ms, 3000, 0, legacy.updated_at_utc_ms
FROM booking_execution_settings AS legacy
WHERE NOT EXISTS (
    SELECT 1
    FROM booking_execution_settings AS newer
    WHERE newer.user_id = legacy.user_id
      AND (
        newer.updated_at_utc_ms > legacy.updated_at_utc_ms
        OR (
            newer.updated_at_utc_ms = legacy.updated_at_utc_ms
            AND newer.credential_id > legacy.credential_id
        )
      )
);
