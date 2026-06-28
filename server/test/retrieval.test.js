import { describe, it, expect, vi, beforeAll } from 'vitest';

beforeAll(() => {
  vi.stubGlobal('fetch', vi.fn(async (url, opts) => {
    // Embedding calls: return a fixed vector so cosine similarity is
    // deterministic. Chat calls (query expansion): return nothing parseable
    // so expandQuery's empty-array fallback kicks in — expansion isn't what
    // this test is verifying.
    if (typeof url === 'string' && url.includes('/api/embeddings')) {
      return { ok: true, json: async () => ({ embedding: new Array(384).fill(0.5) }) };
    }
    return { ok: true, json: async () => ({ message: { content: '' } }) };
  }));
});

describe('semantic retrieval (JSON fallback)', () => {
  it('retrieves an uploaded chunk relevant to the query', async () => {
    const pool = (await import('../src/db.js')).default;
    const { retrieve } = await import('../src/retrieval/retrievalService.js');

    const chat = await pool.query('INSERT INTO chats (user_id, title) VALUES ($1, $2) RETURNING *', ['00000000-0000-0000-0000-000000000000', 'retrieval test']);
    const chatId = chat.rows[0].id;

    const msg = await pool.query('INSERT INTO messages (chat_id, role, content) VALUES ($1, $2, $3) RETURNING *', [chatId, 'user', 'upload']);
    const file = await pool.query(
      'INSERT INTO uploaded_files (message_id, user_id, filename, original_filename, mime_type, size_bytes, file_path) VALUES ($1, $2, $3, $4, $5, $6, $7) RETURNING *',
      [msg.rows[0].id, '00000000-0000-0000-0000-000000000000', 'a.txt', 'a.txt', 'text/plain', 10, '/tmp/a.txt']
    );
    await pool.query(
      'INSERT INTO document_chunks (file_id, content, embedding, page_number) VALUES ($1, $2, $3, $4)',
      [file.rows[0].id, 'Nova AI uses Qdrant for vector search.', JSON.stringify(new Array(384).fill(0.5)), null]
    );

    const result = await retrieve('What does Nova AI use for vector search?', chatId, { topK: 5 });
    expect(result.chunks.length).toBeGreaterThan(0);
    expect(result.contextText).toContain('Qdrant');
  });

  it('returns empty result for a chat with no uploaded documents', async () => {
    const pool = (await import('../src/db.js')).default;
    const { retrieve } = await import('../src/retrieval/retrievalService.js');

    const chat = await pool.query('INSERT INTO chats (user_id, title) VALUES ($1, $2) RETURNING *', ['00000000-0000-0000-0000-000000000000', 'empty chat']);
    const result = await retrieve('anything', chat.rows[0].id, { topK: 5 });
    expect(result.chunks).toEqual([]);
  });

  it('falls back to in-JS cosine search when Qdrant is configured but unreachable', async () => {
    process.env.QDRANT_URL = 'http://127.0.0.1:1'; // nothing listens here
    const pool = (await import('../src/db.js')).default;
    const { semanticSearch } = await import('../src/retrieval/semanticSearch.js');

    const chat = await pool.query('INSERT INTO chats (user_id, title) VALUES ($1, $2) RETURNING *', ['00000000-0000-0000-0000-000000000000', 'qdrant fallback']);
    const chatId = chat.rows[0].id;
    const msg = await pool.query('INSERT INTO messages (chat_id, role, content) VALUES ($1, $2, $3) RETURNING *', [chatId, 'user', 'upload']);
    const file = await pool.query(
      'INSERT INTO uploaded_files (message_id, user_id, filename, original_filename, mime_type, size_bytes, file_path) VALUES ($1, $2, $3, $4, $5, $6, $7) RETURNING *',
      [msg.rows[0].id, '00000000-0000-0000-0000-000000000000', 'b.txt', 'b.txt', 'text/plain', 10, '/tmp/b.txt']
    );
    await pool.query(
      'INSERT INTO document_chunks (file_id, content, embedding, page_number) VALUES ($1, $2, $3, $4)',
      [file.rows[0].id, 'fallback content', JSON.stringify(new Array(384).fill(0.5)), null]
    );

    const results = await semanticSearch('fallback content', chatId, 5);
    expect(results.length).toBeGreaterThan(0);
    delete process.env.QDRANT_URL;
  });
});
