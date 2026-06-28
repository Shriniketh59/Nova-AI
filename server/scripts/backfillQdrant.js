// One-off migration: push existing document_chunks rows (created before
// Qdrant was wired in) into the nova_documents collection. Safe to re-run —
// upsertPoints overwrites by id.
import pool from '../src/db.js';
import { ensureAllCollections, upsertPoints, COLLECTIONS } from '../src/retrieval/qdrantClient.js';

async function main() {
  if (!process.env.QDRANT_URL) {
    console.error('QDRANT_URL not set — point it at your Qdrant instance first.');
    process.exit(1);
  }

  await ensureAllCollections();

  const chunksRes = await pool.query('SELECT * FROM document_chunks', []);
  const filesRes = await pool.query('SELECT id, original_filename FROM uploaded_files', []);
  const filenameByFileId = new Map(filesRes.rows.map(f => [f.id, f.original_filename]));

  const chunks = chunksRes.rows;
  console.log(`Backfilling ${chunks.length} chunks into Qdrant...`);

  const BATCH_SIZE = 100;
  for (let i = 0; i < chunks.length; i += BATCH_SIZE) {
    const batch = chunks.slice(i, i + BATCH_SIZE);
    const points = batch.map(chunk => ({
      id: chunk.id,
      vector: Array.isArray(chunk.embedding) ? chunk.embedding : JSON.parse(chunk.embedding),
      payload: {
        file_id: chunk.file_id,
        content: chunk.content,
        page_number: chunk.page_number ?? null,
        original_filename: filenameByFileId.get(chunk.file_id) || 'unknown document'
      }
    }));
    await upsertPoints(COLLECTIONS.documents.name, points);
    console.log(`  ${Math.min(i + BATCH_SIZE, chunks.length)}/${chunks.length}`);
  }

  console.log('Backfill complete.');
  await pool.end();
}

main().catch(err => {
  console.error('Backfill failed:', err);
  process.exit(1);
});
