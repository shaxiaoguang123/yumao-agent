ALTER TABLE credential_lifecycle_audits
    ADD COLUMN old_account_binding_state TEXT
    CHECK (
        old_account_binding_state IS NULL
        OR old_account_binding_state IN ('unresolved', 'confirmed', 'needs_reconfirmation')
    );
