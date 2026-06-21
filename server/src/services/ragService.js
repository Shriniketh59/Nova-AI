import { retrieve } from '../retrieval/retrievalService.js';
import { buildRagPrompt } from './promptBuilder.js';
import { ReviewAgent } from '../agents/reviewAgent.js';
import logger from '../utils/logger.js';

const OLLAMA_URL = process.env.OLLAMA_URL || 'http://127.0.0.1:11434';
const OLLAMA_MODEL = process.env.OLLAMA_MODEL || 'llama3.2:3b';

const DEFAULT_TOP_K = parseInt(process.env.RAG_TOP_K || '8', 10);

const reviewAgent = new ReviewAgent();

function estimateTokens(text) {
  return Math.ceil((text || '').length / 4);
}

async function callLlm(prompt) {
  const res = await fetch(`${OLLAMA_URL}/api/chat`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      model: OLLAMA_MODEL,
      messages: [{ role: 'user', content: prompt }],
      stream: false,
      options: { temperature: 0.2 }
    })
  });

  if (!res.ok) {
    throw new Error(`LLM request failed with status ${res.status}`);
  }

  const data = await res.json();
  return data.message?.content || '';
}

/**
 * Document-grounded RAG pipeline: hybrid+expanded+reranked retrieval ->
 * grounded prompt -> generate -> review (confidence override + conflict
 * check). This is the strict path — ReviewAgent can replace the answer
 * entirely with the "not found" fallback when confidence is low, unlike the
 * general assistant route in index.js which allows web/model fallback.
 *
 * @param {string} question
 * @param {string} chatId
 * @param {{ topK?: number, threshold?: number }} options
 * @returns {Promise<{ answer: string, sources: Array, confidence: object, conflict: boolean }>}
 */
export async function runRagQuery(question, chatId, options = {}) {
  const topK = options.topK || DEFAULT_TOP_K;

  const { chunks, contextText, sources, confidence } = await retrieve(question, chatId, { topK, ...options });

  logger.info('rag.retrieval', {
    chatId,
    final: chunks.length,
    confidence,
    scores: chunks.map(c => ({ file: c.original_filename, similarity: Number((c.similarity ?? 0).toFixed(3)) }))
  });

  if (chunks.length === 0) {
    const reviewed = await reviewAgent.run('', { chunks, sources, confidence });
    return { answer: reviewed.output.answer, sources: [], confidence, conflict: false };
  }

  logger.info('rag.context', { contextChars: contextText.length, estTokens: estimateTokens(contextText) });

  const prompt = buildRagPrompt(contextText, question);
  const rawAnswer = await callLlm(prompt);

  logger.info('rag.response', { estTokens: estimateTokens(rawAnswer) });

  const reviewed = await reviewAgent.run(rawAnswer, { chunks, sources, confidence });
  return {
    answer: reviewed.output.answer,
    sources: reviewed.output.evidence,
    confidence: reviewed.output.confidence,
    conflict: reviewed.output.conflict
  };
}
