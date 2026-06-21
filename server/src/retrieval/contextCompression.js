// Real implementation — generalized from ragService.js so any agent
// (KnowledgeAgent, ResearchAgent, ...) can reuse the same dedupe/budget
// logic regardless of which search path produced the candidates.

// Removes near-duplicate chunks (same leading text) that retrieval sometimes
// returns when a document has repeated boilerplate or overlapping chunks.
export function dedupeChunks(chunks) {
  const seen = new Set();
  const out = [];
  for (const chunk of chunks) {
    const key = chunk.content.trim().slice(0, 200);
    if (seen.has(key)) continue;
    seen.add(key);
    out.push(chunk);
  }
  return out;
}

// Keeps adding chunks (already sorted by relevance) until the context
// budget is used up, instead of sending every retrieved chunk to the LLM.
export function compressContext(chunks, maxChars) {
  let used = 0;
  const kept = [];
  for (const chunk of chunks) {
    if (used + chunk.content.length > maxChars) break;
    kept.push(chunk);
    used += chunk.content.length;
  }
  return kept;
}

export function estimateTokens(text) {
  return Math.ceil((text || '').length / 4);
}
