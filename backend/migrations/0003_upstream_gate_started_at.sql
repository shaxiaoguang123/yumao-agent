ALTER TABLE upstream_request_gate
    ADD COLUMN active_started_at_utc_ms INTEGER;

CREATE TRIGGER upstream_request_gate_start_timestamp_on_insert
BEFORE INSERT ON upstream_request_gate
WHEN (NEW.lease_owner_id IS NULL AND NEW.active_started_at_utc_ms IS NOT NULL)
  OR (NEW.lease_owner_id IS NOT NULL AND NEW.active_started_at_utc_ms IS NULL)
BEGIN
    SELECT RAISE(ABORT, 'active gate start timestamp must match lease state');
END;

CREATE TRIGGER upstream_request_gate_start_timestamp_on_update
BEFORE UPDATE ON upstream_request_gate
WHEN (NEW.lease_owner_id IS NULL AND NEW.active_started_at_utc_ms IS NOT NULL)
  OR (NEW.lease_owner_id IS NOT NULL AND NEW.active_started_at_utc_ms IS NULL)
BEGIN
    SELECT RAISE(ABORT, 'active gate start timestamp must match lease state');
END;
