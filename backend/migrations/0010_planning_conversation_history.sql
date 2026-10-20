ALTER TABLE planning_conversations
    ADD COLUMN status TEXT NOT NULL DEFAULT 'active'
    CHECK (status IN ('active', 'closed'));

ALTER TABLE planning_conversations
    ADD COLUMN closed_at_utc_ms INTEGER;

CREATE INDEX planning_conversations_history
    ON planning_conversations(user_id, credential_id, conversation_kind, updated_at_utc_ms DESC);
