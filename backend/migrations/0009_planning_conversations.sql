-- Active queue-drafting conversations are scoped to the authenticated user and credential.
CREATE TABLE planning_conversations (
    conversation_id TEXT PRIMARY KEY,
    conversation_kind TEXT NOT NULL CHECK (conversation_kind IN ('queue', 'intent')),
    user_id TEXT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    credential_id TEXT,
    business_date TEXT NOT NULL CHECK (length(business_date) = 10),
    state_json TEXT NOT NULL,
    response_history_json TEXT NOT NULL,
    created_at_utc_ms INTEGER NOT NULL,
    updated_at_utc_ms INTEGER NOT NULL,
    FOREIGN KEY (user_id, credential_id)
        REFERENCES credentials(user_id, credential_id) ON DELETE CASCADE
);

CREATE INDEX planning_conversations_recent
    ON planning_conversations(user_id, credential_id, updated_at_utc_ms DESC);
