-- Carries an auto-generated document object (title/type/summary/content/
-- exportFormats) alongside an AI message's plain-text content, so the
-- DocumentCard export UI can render from persisted state on reload instead
-- of only existing in-memory during the streaming response.
ALTER TABLE messages
  ADD COLUMN IF NOT EXISTS document JSONB;
