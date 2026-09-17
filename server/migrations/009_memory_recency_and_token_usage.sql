-- Migration 009: Add recency, active status, topic tagging to user_memory,
-- and daily token usage tracking table.

ALTER TABLE user_memory
  ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ DEFAULT now(),
  ADD COLUMN IF NOT EXISTS is_active BOOLEAN NOT NULL DEFAULT true,
  ADD COLUMN IF NOT EXISTS topic TEXT;

CREATE INDEX IF NOT EXISTS idx_user_memory_active_user
  ON user_memory(user_id, is_active, updated_at DESC);

-- Everyday token usage tracking per user and date
CREATE TABLE IF NOT EXISTS user_daily_token_usage (
  user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  usage_date DATE NOT NULL DEFAULT CURRENT_DATE,
  prompt_tokens INTEGER NOT NULL DEFAULT 0,
  completion_tokens INTEGER NOT NULL DEFAULT 0,
  total_tokens INTEGER NOT NULL DEFAULT 0,
  updated_at TIMESTAMPTZ DEFAULT now(),
  PRIMARY KEY (user_id, usage_date)
);

CREATE INDEX IF NOT EXISTS idx_user_daily_token_usage_date
  ON user_daily_token_usage(usage_date);
