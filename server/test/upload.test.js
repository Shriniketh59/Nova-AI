import { describe, it, expect, vi, beforeAll } from 'vitest';
import request from 'supertest';

beforeAll(() => {
  // Upload indexing calls generateEmbedding() (rag.js), which hits Ollama
  // over fetch — stub it so this test doesn't need a live Ollama instance.
  vi.stubGlobal('fetch', vi.fn(async () => ({
    ok: true,
    json: async () => ({ embedding: new Array(384).fill(0.01) })
  })));
});

describe('upload + document search workflow', () => {
  it('parses, chunks, and embeds an uploaded text file', async () => {
    const app = (await import('../src/index.js')).default;

    const res = await request(app)
      .post('/api/upload')
      .attach('file', Buffer.from('Nova AI is a local-first agentic assistant.'), {
        filename: 'note.txt',
        contentType: 'text/plain'
      });

    expect(res.status).toBe(201);
    expect(res.body.success).toBe(true);
    expect(res.body.file.name).toBe('note.txt');
  });
});
