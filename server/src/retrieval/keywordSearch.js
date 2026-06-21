import { fetchChunksForChat } from '../rag.js';

// Lightweight BM25-lite lexical scorer — no external index, runs over the
// same in-memory chunk pool semanticSearch uses. Catches exact-term matches
// (codes, names, acronyms) that embedding similarity sometimes misses.
const STOPWORDS = new Set(['the', 'a', 'an', 'is', 'are', 'was', 'were', 'of', 'to', 'in', 'on', 'for', 'and', 'or', 'with', 'what', 'how', 'do', 'does', 'i']);

function tokenize(text) {
  return (text || '')
    .toLowerCase()
    .match(/[a-z0-9]+/g) || [];
}

function termFreqScore(queryTerms, chunkText) {
  const chunkTerms = tokenize(chunkText);
  if (chunkTerms.length === 0) return 0;
  const chunkTermSet = new Map();
  for (const t of chunkTerms) chunkTermSet.set(t, (chunkTermSet.get(t) || 0) + 1);

  let score = 0;
  for (const qt of queryTerms) {
    const tf = chunkTermSet.get(qt) || 0;
    if (tf > 0) {
      // log-dampened term frequency, normalized by chunk length (BM25-ish without IDF corpus stats)
      score += (1 + Math.log(tf)) / Math.sqrt(chunkTerms.length);
    }
  }
  return score;
}

export async function keywordSearch(query, chatId, topK = 10) {
  const queryTerms = [...new Set(tokenize(query).filter(t => !STOPWORDS.has(t) && t.length > 1))];
  if (queryTerms.length === 0) return [];

  const chunks = await fetchChunksForChat(chatId);
  if (chunks.length === 0) return [];

  const scored = chunks
    .map(chunk => ({ ...chunk, keywordScore: termFreqScore(queryTerms, chunk.content) }))
    .filter(c => c.keywordScore > 0);

  scored.sort((a, b) => b.keywordScore - a.keywordScore);
  return scored.slice(0, topK);
}
