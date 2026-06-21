import { BaseAgent } from './baseAgent.js';
import pool from '../db.js';

// Real, deliberately lightweight implementation: reuses the existing
// `messages` table as the memory store instead of a new schema (every user
// message in a chat already IS a persisted fact/preference/project detail).
// Retrieval is keyword-overlap, not embeddings — avoids an extra Ollama
// round-trip on every query, keeping memory lookup near-free.
// Priority order this enforces: Retrieved Sources > Memory > Model Knowledge
// — memory is only surfaced here, callers decide where it ranks in the prompt.
const STOPWORDS = new Set(['the', 'a', 'an', 'is', 'are', 'was', 'were', 'of', 'to', 'in', 'on', 'for', 'and', 'or', 'with', 'what', 'how', 'do', 'does', 'i', 'you', 'my']);

function tokenize(text) {
  return (text || '').toLowerCase().match(/[a-z0-9]+/g) || [];
}

export class MemoryAgent extends BaseAgent {
  constructor() {
    super('MemoryAgent');
  }

  async run(query, context = {}) {
    const { chatId, excludeMessageId, topK = 3 } = context;
    try {
      const memories = await this.getRelevantMemories(chatId, query, excludeMessageId, topK);
      return { success: true, output: { memories } };
    } catch (err) {
      return { success: false, output: { memories: [] }, error: err.message };
    }
  }

  async getRelevantMemories(chatId, query, excludeMessageId = null, topK = 3) {
    if (!chatId) return [];

    const res = await pool.query(
      'SELECT * FROM messages WHERE chat_id = $1 ORDER BY created_at ASC',
      [chatId]
    );
    const pastUserMessages = res.rows.filter(m => m.role === 'user' && m.id !== excludeMessageId);
    if (pastUserMessages.length === 0) return [];

    const queryTerms = new Set(tokenize(query).filter(t => !STOPWORDS.has(t) && t.length > 1));
    if (queryTerms.size === 0) return [];

    const scored = pastUserMessages.map(m => {
      const msgTerms = tokenize(m.content);
      const overlap = msgTerms.filter(t => queryTerms.has(t)).length;
      return { content: m.content, createdAt: m.created_at, score: overlap };
    }).filter(m => m.score > 0);

    scored.sort((a, b) => b.score - a.score || new Date(b.createdAt) - new Date(a.createdAt));
    return scored.slice(0, topK).map(m => m.content);
  }
}

export const memoryAgent = new MemoryAgent();
