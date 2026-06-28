-- Cross-session/long-chat context management: once a chat's message history
-- exceeds the prompt budget, older turns get summarized once and cached
-- here instead of re-summarizing (or truncating silently) on every turn.
ALTER TABLE chats
  ADD COLUMN IF NOT EXISTS summary TEXT,
  ADD COLUMN IF NOT EXISTS summary_updated_at TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS summary_message_count INTEGER NOT NULL DEFAULT 0;
