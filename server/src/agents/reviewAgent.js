import { BaseAgent } from './baseAgent.js';
import { cosineSimilarity } from '../rag.js';

const NOT_FOUND_MESSAGE = 'Reliable information was not found in the available sources.';
const CONFLICT_SIMILARITY_THRESHOLD = 0.3; // below this, two on-topic chunks are considered divergent

// Final decision-making step: Question -> Retrieve -> Validate -> Compare ->
// Generate -> Review -> Return. This agent is the "Review" stage — it
// doesn't call the LLM again (cheap, no added latency on the hot path), it
// validates the answer's grounding using retrieval signal already computed:
// low confidence -> override with the "not found" fallback instead of
// letting a hallucinated-sounding answer through; divergent sources ->
// flag the conflict explicitly rather than silently picking one.
export class ReviewAgent extends BaseAgent {
  constructor() {
    super('ReviewAgent');
  }

  async run(answer, context = {}) {
    const { chunks = [], sources = [], confidence = { score: 0, label: 'low' } } = context;

    if (confidence.label === 'low' || chunks.length === 0) {
      return {
        success: true,
        output: {
          answer: NOT_FOUND_MESSAGE,
          evidence: sources,
          confidence,
          conflict: false
        }
      };
    }

    const conflict = detectConflict(chunks);

    let finalAnswer = answer;
    if (conflict.found) {
      finalAnswer = `${answer}\n\nNote: sources disagree on this point (${conflict.detail}) — treat with caution.`;
    }

    return {
      success: true,
      output: {
        answer: finalAnswer,
        evidence: sources,
        confidence,
        conflict: conflict.found,
        conflictDetail: conflict.found ? conflict.detail : null
      }
    };
  }
}

// Heuristic: two chunks from different files that both scored above the
// retrieval threshold for the same query, but whose embeddings are far apart,
// are "on-topic but divergent" — a proxy for conflicting information without
// a second LLM call to actually read and compare claims.
function detectConflict(chunks) {
  const distinctFileChunks = [];
  const seenFiles = new Set();
  for (const c of chunks) {
    if (!c.embedding || seenFiles.has(c.original_filename)) continue;
    seenFiles.add(c.original_filename);
    distinctFileChunks.push(c);
  }

  for (let i = 0; i < distinctFileChunks.length; i++) {
    for (let j = i + 1; j < distinctFileChunks.length; j++) {
      const sim = cosineSimilarity(distinctFileChunks[i].embedding, distinctFileChunks[j].embedding);
      if (sim < CONFLICT_SIMILARITY_THRESHOLD) {
        return {
          found: true,
          detail: `${distinctFileChunks[i].original_filename} vs ${distinctFileChunks[j].original_filename}`
        };
      }
    }
  }
  return { found: false, detail: null };
}
