import pool from '../db.js';
import { compressContext, estimateTokens } from '../retrieval/contextCompression.js';
import logger from './logger.js';

const OLLAMA_URL = process.env.OLLAMA_URL || 'http://127.0.0.1:11434';
const OLLAMA_MODEL = process.env.OLLAMA_MODEL || 'llama3.2:3b';
// Don't re-summarize every turn — only once enough new messages have piled
// up since the last summary to be worth the extra Ollama round-trip.
const SUMMARY_REFRESH_THRESHOLD = parseInt(process.env.SUMMARY_REFRESH_THRESHOLD || '20', 10);

async function summarize(messages) {
  const transcript = messages.map(m => `${m.role}: ${m.content}`).join('\n');
  try {
    const res = await fetch(`${OLLAMA_URL}/api/chat`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        model: OLLAMA_MODEL,
        stream: false,
        options: { temperature: 0.2 },
        messages: [
          { role: 'system', content: 'Summarize this conversation in 3-5 sentences: key facts established, decisions made, and the user\'s stated preferences/goals. Be specific, not generic.' },
          { role: 'user', content: transcript }
        ]
      })
    });
    if (!res.ok) throw new Error(`Summary call failed: ${res.status}`);
    const data = await res.json();
    return data.message?.content || '';
  } catch (err) {
    logger.warn('contextManager.summarize.failed', { error: err.message });
    return '';
  }
}

// Returns a context block for the prompt: a cached summary of older turns
// (refreshed only every SUMMARY_REFRESH_THRESHOLD new messages) plus the
// most recent messages verbatim, budgeted to maxChars — so long chats don't
// blow the prompt window the way sending full history would.
export async function getConversationContext(chatId, maxChars = 3000) {
  if (!chatId) return '';

  const chatRes = await pool.query('SELECT summary, summary_message_count FROM chats WHERE id = $1', [chatId]);
  const { summary: cachedSummary = null, summary_message_count: summaryMessageCount = 0 } = chatRes.rows[0] || {};

  const messagesRes = await pool.query('SELECT * FROM messages WHERE chat_id = $1 ORDER BY created_at ASC', [chatId]);
  const messages = messagesRes.rows;

  const newSinceSummary = messages.length - summaryMessageCount;
  let summary = cachedSummary;

  if (newSinceSummary >= SUMMARY_REFRESH_THRESHOLD) {
    const toSummarize = messages.slice(0, messages.length - 5); // leave the last 5 out, they're sent verbatim below anyway
    if (toSummarize.length > 0) {
      summary = await summarize(toSummarize);
      await pool.query(
        'UPDATE chats SET summary = $1, summary_updated_at = CURRENT_TIMESTAMP, summary_message_count = $2 WHERE id = $3',
        [summary, messages.length, chatId]
      );
    }
  }

  const recentMessages = messages.slice(-5).map(m => ({ content: `${m.role}: ${m.content}` }));
  const recentBudget = summary ? maxChars - summary.length - 50 : maxChars;
  const recentKept = compressContext(recentMessages, Math.max(recentBudget, 0));

  const blocks = [];
  if (summary) blocks.push(`[Earlier in this conversation]\n${summary}`);
  if (recentKept.length > 0) blocks.push(`[Recent messages]\n${recentKept.map(m => m.content).join('\n')}`);

  const contextText = blocks.join('\n\n');
  logger.info('contextManager.context', { chatId, totalMessages: messages.length, hasSummary: !!summary, estimatedTokens: estimateTokens(contextText) });
  return contextText;
}
