import { generateEmbedding } from '../rag.js';
import { hybridSearch } from './hybridSearch.js';
import { expandQuery } from './queryExpansion.js';
import { rerank } from './reranker.js';
import { dedupeChunks, compressContext } from './contextCompression.js';
import { attributeSources } from './sourceAttribution.js';
import { cacheKey, getCached, setCached } from '../jobs/cache.js';
import logger from '../utils/logger.js';

const DEFAULT_TOP_K = parseInt(process.env.RAG_TOP_K || '8', 10); // target 5-10 high quality chunks
const DEFAULT_THRESHOLD = parseFloat(process.env.RAG_SIMILARITY_THRESHOLD || '0.25');
const MAX_CONTEXT_CHARS = parseInt(process.env.RAG_MAX_CONTEXT_CHARS || '6000', 10);

// Confidence is derived purely from retrieval signal (top score + how many
// chunks agree), not a second LLM call — keeps this on the hot path cheap.
// Maps to the response contract's "Confidence: NN%" + low/med/high label.
function computeConfidence(chunks) {
  if (chunks.length === 0) {
    return { score: 0, label: 'low' };
  }
  const topScore = chunks[0].similarity ?? chunks[0].hybridScore ?? 0;
  const supportBonus = Math.min(chunks.length, 5) * 0.03;
  const score = Math.max(0, Math.min(1, topScore + supportBonus));
  const label = score >= 0.6 ? 'high' : score >= 0.35 ? 'medium' : 'low';
  return { score: Number((score * 100).toFixed(0)), label };
}

/**
 * Single entry point for "go get me relevant, deduplicated, ranked context".
 * Pipeline: multi-query expansion -> hybrid (semantic+keyword) search per
 * variant -> merge -> MMR rerank -> dedupe -> context-budget compression ->
 * confidence scoring. Cached per (query, chatId) for repeat questions.
 *
 * @returns {Promise<{ chunks: Array, contextText: string, sources: Array, confidence: {score:number, label:string} }>}
 */
export async function retrieve(query, chatId, options = {}) {
  const topK = options.topK || DEFAULT_TOP_K;
  const threshold = options.threshold ?? DEFAULT_THRESHOLD;

  const key = cacheKey(query, chatId);
  const cached = getCached(key);
  if (cached) return cached;

  const [queryVector, expansions] = await Promise.all([
    generateEmbedding(query),
    expandQuery(query)
  ]);

  const variants = [query, ...expansions];

  // Multi-query retrieval: union candidates from the original + expanded
  // phrasings, keeping each chunk's best score across variants.
  const candidateMap = new Map();
  const variantResults = await Promise.all(
    variants.map(v => hybridSearch(v, chatId, topK * 3))
  );
  for (const results of variantResults) {
    for (const chunk of results) {
      const existing = candidateMap.get(chunk.id);
      if (!existing || chunk.hybridScore > existing.hybridScore) {
        candidateMap.set(chunk.id, chunk);
      }
    }
  }

  const candidates = [...candidateMap.values()];
  const aboveThreshold = candidates.filter(c => (c.similarity ?? 0) >= threshold || c.keywordScore > 0);

  const reranked = await rerank(queryVector, aboveThreshold, topK * 2);
  const deduped = dedupeChunks(reranked);
  const finalChunks = compressContext(deduped, MAX_CONTEXT_CHARS).slice(0, topK);

  logger.info('retrieval.pipeline', {
    chatId,
    variants: variants.length,
    candidates: candidates.length,
    aboveThreshold: aboveThreshold.length,
    final: finalChunks.length
  });

  const contextText = finalChunks.map(c => c.content).join('\n---\n');
  const sources = attributeSources(finalChunks);
  const confidence = computeConfidence(finalChunks);

  const result = { chunks: finalChunks, contextText, sources, confidence };
  setCached(key, result);
  return result;
}
