import { cosineSimilarity } from '../rag.js';

// No cross-encoder model is available locally (CPU-only Ollama box), so this
// reranks using Maximal Marginal Relevance over the embeddings already
// computed during retrieval: balances relevance to the query against
// redundancy with chunks already selected, instead of just taking the top-N
// by raw score (which tends to return 5 near-duplicate chunks from the same
// paragraph).
const MMR_LAMBDA = 0.7; // weight toward relevance vs diversity

export async function rerank(queryVector, candidates, topK = 8) {
  if (candidates.length === 0) return [];

  const pool = candidates.map(c => ({
    ...c,
    relevance: c.embedding ? cosineSimilarity(queryVector, c.embedding) : (c.hybridScore || 0)
  }));

  const selected = [];
  const remaining = [...pool];

  while (selected.length < topK && remaining.length > 0) {
    let bestIdx = 0;
    let bestScore = -Infinity;

    for (let i = 0; i < remaining.length; i++) {
      const candidate = remaining[i];
      const maxSimToSelected = selected.length === 0
        ? 0
        : Math.max(...selected.map(s => (
          candidate.embedding && s.embedding ? cosineSimilarity(candidate.embedding, s.embedding) : 0
        )));
      const mmrScore = MMR_LAMBDA * candidate.relevance - (1 - MMR_LAMBDA) * maxSimToSelected;
      if (mmrScore > bestScore) {
        bestScore = mmrScore;
        bestIdx = i;
      }
    }

    const [picked] = remaining.splice(bestIdx, 1);
    selected.push({ ...picked, rerankScore: bestScore });
  }

  return selected;
}
