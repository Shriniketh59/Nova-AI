import { BaseAgent } from './baseAgent.js';
import { retrieve } from '../retrieval/retrievalService.js';
import { generateEmbedding, cosineSimilarity } from '../rag.js';
import { tierFor } from '../retrieval/complexity.js';
import { rankSources, countTrustTiers } from '../retrieval/sourceTrust.js';

const RAG_API_URL = process.env.RAG_API_URL || 'http://127.0.0.1:8008';
const CONTRADICTION_THRESHOLD = 0.3;

// Contested-fact categories: getting these wrong is the whole problem
// statement (wrong founder, wrong DOB, wrong director) — never answer
// purely from an uploaded doc without also checking official/reference
// sources, even though "Uploaded Document > Web Search" is the default
// priority order for every other category.
const FORCE_WEB_SEARCH_CATEGORIES = new Set(['biography', 'politics', 'medical', 'legal', 'finance', 'news']);

// Atomic-fact extraction for the cheap cross-source agreement check —
// regex, not NLP: catches "wrong year/date/number" without a new ML
// dependency, per the brief's explicit hallucination examples (wrong DOB,
// wrong founding year).
const YEAR_RE = /\b(1[89]\d{2}|20\d{2})\b/g;
const DATE_RE = /\b\d{1,2}\s+(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{4}\b/gi;

function extractFacts(text) {
  if (!text) return { years: [], dates: [] };
  return {
    years: [...new Set((text.match(YEAR_RE) || []))],
    dates: [...new Set((text.match(DATE_RE) || []))]
  };
}

// Same proper-noun-overlap heuristic used to decide "are these two snippets
// even about the same thing" before comparing facts — two sources both
// mentioning dates but about different people/companies isn't a contradiction.
function sharesProperNoun(textA, textB) {
  const nouns = (t) => new Set((t.match(/\b[A-Z][a-z]{2,}\b/g) || []));
  const a = nouns(textA);
  const b = nouns(textB);
  for (const n of a) if (b.has(n)) return true;
  return false;
}

export function detectFactDisagreements(evidence) {
  const disagreements = [];
  for (let i = 0; i < evidence.length; i++) {
    for (let j = i + 1; j < evidence.length; j++) {
      const a = evidence[i];
      const b = evidence[j];
      const textA = a.snippet || '';
      const textB = b.snippet || '';
      if (!sharesProperNoun(textA, textB)) continue;

      const factsA = extractFacts(textA);
      const factsB = extractFacts(textB);
      const yearsA = factsA.years;
      const yearsB = factsB.years;
      if (yearsA.length > 0 && yearsB.length > 0 && !yearsA.some(y => yearsB.includes(y))) {
        disagreements.push({
          sourceA: a.title || a.filename, sourceB: b.title || b.filename,
          factType: 'year', valueA: yearsA.join(', '), valueB: yearsB.join(', ')
        });
      }
    }
  }
  return disagreements;
}

// Second stage of the critical-thinking pipeline: Memory Retrieval already
// happened upstream (SupervisorAgent), this is the RAG Retrieval + Evidence
// Analysis step. Fans out to document retrieval (hybrid+expansion+rerank,
// already built in retrievalService.js) AND web search in parallel, then
// builds one evidence list spanning both — "never rely on one source".
export class ResearchAgent extends BaseAgent {
  constructor() {
    super('ResearchAgent');
  }

  async run(question, context = {}) {
    const { chatId, plan = {}, hasFiles = false, memories = [], forceTopK = null } = context;
    // Planner's needsWebSearch boolean is noisy at the LLM sampling level —
    // observed it flip to false for plainly factual questions even when
    // taskType was correctly classified "factual". Trust taskType instead:
    // only skip web search for genuine greetings/small talk, never silently
    // skip evidence-gathering for anything that needs grounding. An attached
    // file always wins though — Uploaded Document > Web Search per priority order.
    const forceWebSearch = FORCE_WEB_SEARCH_CATEGORIES.has(plan.category);
    const skipWebSearch = (hasFiles && !forceWebSearch) || plan.taskType === 'greeting';
    // Source-count scales with question complexity: 3 for a quick factual
    // ask, up to 10-20 for research-grade questions — "never answer using
    // only 1 source" applies at every tier.
    const tier = forceTopK ? { topK: forceTopK, minSources: tierFor(question).minSources } : tierFor(question);
    try {
      const [docResult, webSources] = await Promise.all([
        plan.needsDocRetrieval !== false ? retrieve(question, chatId, { topK: tier.topK }) : Promise.resolve({ chunks: [], sources: [], contextText: '', confidence: { score: 0, label: 'low' } }),
        !skipWebSearch ? fetchWebSources(question, tier.topK) : Promise.resolve([])
      ]);

      // Priority order: Uploaded Files > User Memory > Web Search. Doc
      // retrieval above is already scoped to this chat's uploaded files;
      // memory (earlier-in-conversation facts) ranks above web because it's
      // first-party context, web fills remaining slots up to the tier target.
      const rankedWebSources = rankSources(webSources);
      const evidence = [
        ...docResult.sources.map((s, i) => ({ ...s, snippet: docResult.chunks[i]?.content?.slice(0, 400) || '' })),
        ...memories.map(m => ({ title: 'Earlier in this conversation', type: 'memory', snippet: m })),
        ...rankedWebSources.map(s => ({ title: s.title, type: 'web', url: s.url, snippet: s.snippet, trustTier: s.trustTier }))
      ].slice(0, tier.topK);

      const trustTiers = countTrustTiers(evidence);
      const [embeddingContradictions, factDisagreements] = await Promise.all([
        detectContradictions(evidence),
        Promise.resolve(detectFactDisagreements(evidence))
      ]);
      const contradictions = [...embeddingContradictions, ...factDisagreements];

      const evidenceSummary = evidence.length > 0
        ? evidence.map((e, i) => `[${i + 1}] (${e.type}) ${e.title || e.filename}: ${e.snippet}`).join('\n\n')
        : 'No external evidence found — answer must rely on general knowledge only.';

      return {
        success: true,
        output: {
          evidence,
          evidenceSummary,
          contradictions,
          docConfidence: docResult.confidence,
          sourceCount: evidence.length,
          minSources: tier.minSources,
          trustTiers,
          category: plan.category || 'general'
        }
      };
    } catch (err) {
      return { success: false, output: { evidence: [], evidenceSummary: '', contradictions: [] }, error: err.message };
    }
  }
}

async function fetchWebSources(query, maxResults = 5) {
  try {
    const res = await fetch(`${RAG_API_URL}/search`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ query, max_results: maxResults })
    });
    if (!res.ok) return [];
    const data = await res.json();
    return data.sources || [];
  } catch {
    return [];
  }
}

// Pairwise-compares evidence snippet embeddings; on-topic items whose
// embeddings are far apart are flagged as a probable contradiction, same
// heuristic as reviewAgent.js's doc-only conflict check but generalized
// across doc+web evidence here.
async function detectContradictions(evidence) {
  if (evidence.length < 2) return [];

  const withEmbeddings = await Promise.all(
    evidence.map(async e => ({ ...e, _vec: await generateEmbedding(e.snippet || e.title || '').catch(() => null) }))
  );

  const contradictions = [];
  for (let i = 0; i < withEmbeddings.length; i++) {
    for (let j = i + 1; j < withEmbeddings.length; j++) {
      const a = withEmbeddings[i];
      const b = withEmbeddings[j];
      if (!a._vec || !b._vec) continue;
      const sim = cosineSimilarity(a._vec, b._vec);
      if (sim < CONTRADICTION_THRESHOLD) {
        contradictions.push({ sourceA: a.title || a.filename, sourceB: b.title || b.filename, similarity: Number(sim.toFixed(2)) });
      }
    }
  }
  return contradictions;
}
