import { describe, it, expect, vi, beforeAll } from 'vitest';

beforeAll(() => {
  // extractMemory/getRelevantMemories call generateEmbedding() over fetch —
  // return a fixed vector so cosine similarity is deterministic in this test.
  vi.stubGlobal('fetch', vi.fn(async () => ({
    ok: true,
    json: async () => ({ embedding: new Array(384).fill(0.5) })
  })));
});

describe('memory recall', () => {
  it('extracts a stated preference and recalls it for a related later query', async () => {
    const { memoryAgent } = await import('../src/agents/memoryAgent.js');
    const { DEFAULT_USER_ID } = await import('../src/db.js');

    await memoryAgent.extractMemory(DEFAULT_USER_ID, null, 'Remember my name is Shrini');

    const memories = await memoryAgent.getRelevantMemories(null, 'what is my name?');
    expect(memories.some(m => m.includes('Shrini'))).toBe(true);
  });

  it('does not store memory for messages without a preference/fact trigger', async () => {
    const { memoryAgent } = await import('../src/agents/memoryAgent.js');
    const { DEFAULT_USER_ID } = await import('../src/db.js');

    const before = await memoryAgent.getRelevantMemories(null, 'name');
    await memoryAgent.extractMemory(DEFAULT_USER_ID, null, 'what time is it');
    const after = await memoryAgent.getRelevantMemories(null, 'name');

    expect(after.length).toBe(before.length);
  });
});
