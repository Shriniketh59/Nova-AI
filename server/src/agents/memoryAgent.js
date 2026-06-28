import { BaseAgent } from './baseAgent.js';
import pool, { DEFAULT_USER_ID } from '../db.js';
import { generateEmbedding, cosineSimilarity } from '../rag.js';

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
    const [shortTerm, longTerm] = await Promise.all([
      this._shortTermMemories(chatId, query, excludeMessageId, topK),
      this._longTermMemories(query, topK).catch(() => [])
    ]);
    // Short-term (this conversation) ranks first — it's what the user just
    // said, more relevant than an old stored preference unless nothing
    // current matches.
    return [...shortTerm, ...longTerm].slice(0, topK + 2);
  }

  async _shortTermMemories(chatId, query, excludeMessageId, topK) {
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

  // Long-term/global memory: semantic similarity against user_memory,
  // which holds facts/preferences extracted across all chats (not just this
  // one) — see extractMemory(). Embedding-based since these entries don't
  // share vocabulary with the current query the way an in-chat message does.
  async _longTermMemories(query, topK = 3) {
    const res = await pool.query('SELECT * FROM user_memory WHERE user_id = $1', [DEFAULT_USER_ID]);
    if (res.rows.length === 0) return [];

    const queryVector = await generateEmbedding(query);
    const scored = res.rows.map(m => ({
      content: m.content,
      score: cosineSimilarity(queryVector, m.embedding)
    })).filter(m => m.score >= 0.5);

    scored.sort((a, b) => b.score - a.score);
    return scored.slice(0, topK).map(m => m.content);
  }

  // Bounded extraction: only fires when the user's message looks like it
  // states a durable fact/preference (heuristic gate), not on every turn —
  // keeps this near-free instead of an LLM call per message.
  async extractMemory(userId, chatId, userMessage) {
    const MEMORY_TRIGGER_RE = /\b(remember|my name is|i prefer|i like|i'm working on|i am working on|call me|always (use|write|respond)|never (use|write))\b/i;
    if (!MEMORY_TRIGGER_RE.test(userMessage)) return;

    try {
      const embedding = await generateEmbedding(userMessage);
      await pool.query(
        'INSERT INTO user_memory (user_id, chat_id, type, content, embedding) VALUES ($1, $2, $3, $4, $5)',
        [userId, chatId, 'preference', userMessage, JSON.stringify(embedding)]
      );
    } catch (err) {
      console.warn('⚠️ Memory extraction failed (non-fatal):', err.message);
    }
  }
}

export const memoryAgent = new MemoryAgent();
