import { semanticSearch } from './semanticSearch.js';
import { keywordSearch } from './keywordSearch.js';

const RRF_K = 60; // standard reciprocal-rank-fusion constant

// Fuses semantic (embedding cosine) and keyword (lexical) result lists via
// Reciprocal Rank Fusion: a chunk's score is the sum of 1/(k+rank) across
// whichever list(s) it appears in. This means a chunk ranked #1 by keyword
// match but missed entirely by semantic search (or vice versa) still surfaces,
// instead of being lost to a single scoring method.
export async function hybridSearch(query, chatId, topK = 10) {
  const [semanticResults, keywordResults] = await Promise.all([
    semanticSearch(query, chatId, topK * 2),
    keywordSearch(query, chatId, topK * 2)
  ]);

  const fused = new Map();

  semanticResults.forEach((chunk, rank) => {
    const rrf = 1 / (RRF_K + rank + 1);
    fused.set(chunk.id, { ...chunk, hybridScore: rrf, similarity: chunk.similarity });
  });

  keywordResults.forEach((chunk, rank) => {
    const rrf = 1 / (RRF_K + rank + 1);
    const existing = fused.get(chunk.id);
    if (existing) {
      existing.hybridScore += rrf;
      existing.keywordScore = chunk.keywordScore;
    } else {
      fused.set(chunk.id, { ...chunk, hybridScore: rrf });
    }
  });

  const merged = [...fused.values()];
  merged.sort((a, b) => b.hybridScore - a.hybridScore);
  return merged.slice(0, topK);
}
