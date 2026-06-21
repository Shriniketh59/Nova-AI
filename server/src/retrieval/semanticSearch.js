import { generateEmbedding, searchRelevantChunks } from '../rag.js';

// Real path today: delegates to the existing Postgres/JSON-fallback cosine
// search in rag.js. Once Qdrant is live, this function's body swaps to
// qdrantClient.search() against the relevant collection — callers
// (retrievalService.js) don't change.
export async function semanticSearch(query, chatId, topK = 10) {
  return searchRelevantChunks(query, chatId, topK);
}

export async function embedQuery(query) {
  return generateEmbedding(query);
}
