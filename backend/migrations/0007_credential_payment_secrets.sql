CREATE TABLE credential_payment_secrets (
    user_id TEXT NOT NULL,
    credential_id TEXT NOT NULL,
    secret_revision INTEGER NOT NULL CHECK (secret_revision > 0),
    ciphertext BLOB NOT NULL,
    nonce BLOB NOT NULL CHECK (length(nonce) = 12),
    tag BLOB NOT NULL CHECK (length(tag) = 16),
    encryption_key_version TEXT NOT NULL,
    updated_at_utc_ms INTEGER NOT NULL,
    PRIMARY KEY (user_id, credential_id),
    FOREIGN KEY (user_id, credential_id)
        REFERENCES credentials(user_id, credential_id) ON DELETE RESTRICT
);
