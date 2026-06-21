-- Extends the file/chunk tracking schema for multimodal sources and Qdrant
-- migration. Not yet applied automatically by db.js's initDb() — run
-- manually against Postgres when ready to move off the JSON fallback /
-- single-collection cosine search.

ALTER TABLE uploaded_files
  ADD COLUMN IF NOT EXISTS source_type TEXT NOT NULL DEFAULT 'document', -- document|code|web|youtube|audio|video
  ADD COLUMN IF NOT EXISTS ingest_status TEXT NOT NULL DEFAULT 'pending', -- pending|processing|indexed|failed
  ADD COLUMN IF NOT EXISTS qdrant_collection TEXT,
  ADD COLUMN IF NOT EXISTS source_url TEXT;

-- document_chunks keeps its JSON embedding column for the current local
-- fallback path. Once Qdrant is live, this table holds metadata only and
-- the vector itself moves to Qdrant's payload+vector store.
ALTER TABLE document_chunks
  ADD COLUMN IF NOT EXISTS page_number INTEGER,
  ADD COLUMN IF NOT EXISTS line_start INTEGER,
  ADD COLUMN IF NOT EXISTS line_end INTEGER,
  ADD COLUMN IF NOT EXISTS qdrant_point_id UUID;

CREATE TABLE IF NOT EXISTS indexing_jobs (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  file_id UUID REFERENCES uploaded_files(id),
  status TEXT NOT NULL DEFAULT 'queued', -- queued|running|done|failed
  error TEXT,
  created_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now()
);
