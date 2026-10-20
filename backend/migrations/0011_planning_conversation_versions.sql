ALTER TABLE planning_conversations
    ADD COLUMN version INTEGER NOT NULL DEFAULT 1 CHECK (version >= 1);
