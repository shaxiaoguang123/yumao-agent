CREATE TABLE ai_models (
    model_id TEXT NOT NULL PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(user_id),
    name TEXT NOT NULL,
    base_url TEXT NOT NULL,
    model TEXT NOT NULL,
    auth_mode TEXT NOT NULL CHECK (auth_mode IN ('bearer', 'none')),
    api_key_ciphertext BLOB,
    api_key_nonce BLOB,
    api_key_tag BLOB,
    encryption_key_id TEXT,
    key_revision TEXT NOT NULL,
    version INTEGER NOT NULL CHECK (version > 0),
    created_at_utc_ms INTEGER NOT NULL,
    updated_at_utc_ms INTEGER NOT NULL,
    UNIQUE(user_id, model_id),
    CHECK ((api_key_ciphertext IS NULL AND api_key_nonce IS NULL AND api_key_tag IS NULL AND encryption_key_id IS NULL)
        OR (api_key_ciphertext IS NOT NULL AND api_key_nonce IS NOT NULL AND api_key_tag IS NOT NULL AND encryption_key_id IS NOT NULL))
);
CREATE INDEX ai_models_by_user ON ai_models(user_id, created_at_utc_ms, model_id);

CREATE TABLE ai_model_preferences (
    user_id TEXT NOT NULL PRIMARY KEY REFERENCES users(user_id),
    selected_model_id TEXT,
    default_model_id TEXT,
    updated_at_utc_ms INTEGER NOT NULL
);
