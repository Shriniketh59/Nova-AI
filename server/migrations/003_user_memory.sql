-- Long-term/project memory store, separate from the per-chat `messages`
-- keyword-overlap lookup memoryAgent.js already does. chat_id NULL means
-- global/user-level memory (preferences); chat_id set scopes it to one
-- project/chat thread.
CREATE TABLE IF NOT EXISTS user_memory (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  chat_id UUID REFERENCES chats(id) ON DELETE CASCADE,
  type TEXT NOT NULL DEFAULT 'fact', -- preference|project|fact
  content TEXT NOT NULL,
  embedding JSONB NOT NULL,
  created_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_user_memory_user_id ON user_memory(user_id);
CREATE INDEX IF NOT EXISTS idx_user_memory_chat_id ON user_memory(chat_id);
