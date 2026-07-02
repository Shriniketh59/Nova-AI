-- DSA/coding interview coach: LLM-generated practice problems, per-user
-- session tracking, and submission history. No code execution — feedback
-- comes from static validation + LLM critique (see routes/interview_coach.py).
CREATE TABLE IF NOT EXISTS practice_problems (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL,
  title TEXT NOT NULL,
  difficulty TEXT NOT NULL,        -- easy|medium|hard
  category TEXT NOT NULL,          -- arrays|strings|dp|graphs|trees|...
  description TEXT NOT NULL,
  constraints TEXT,
  example_input TEXT,
  example_output TEXT,
  created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS interview_sessions (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL,
  problem_id UUID NOT NULL REFERENCES practice_problems(id) ON DELETE CASCADE,
  status TEXT NOT NULL DEFAULT 'in_progress', -- in_progress|solved|abandoned
  attempts INTEGER NOT NULL DEFAULT 0,
  best_confidence INTEGER,
  created_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS session_submissions (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  session_id UUID NOT NULL REFERENCES interview_sessions(id) ON DELETE CASCADE,
  code TEXT NOT NULL,
  language TEXT NOT NULL,
  validation JSONB NOT NULL,
  confidence JSONB NOT NULL,
  feedback TEXT,
  created_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_sessions_user_id ON interview_sessions(user_id);
CREATE INDEX IF NOT EXISTS idx_submissions_session_id ON session_submissions(session_id);
