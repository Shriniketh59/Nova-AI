-- SHA256(file_bytes) dedup, mirroring the sret-rag "doc dedup rule":
-- if a file with the same hash is already indexed, skip the whole
-- parse->chunk->embed pipeline instead of re-processing.
ALTER TABLE uploaded_files
  ADD COLUMN IF NOT EXISTS file_hash TEXT;

CREATE INDEX IF NOT EXISTS idx_uploaded_files_hash ON uploaded_files(user_id, file_hash);
