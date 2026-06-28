// Cheap heuristic (no LLM call) classifying question complexity into the
// source-count tiers the product spec requires: simple/medium/complex/research.
// Mirrors Chat.jsx's client-side isComplexPrompt but produces a tier instead
// of a binary fast/deep routing decision — used purely to size retrieval,
// never to decide which pipeline runs.
const RESEARCH_KEYWORDS = /\b(research|in depth|comprehensive|thorough|literature|survey of|state of the art)\b/i;
const COMPLEX_KEYWORDS = /\b(compare|comparison|vs\.?|versus|difference between|pros and cons|analyze|analyse|evaluate|trade-?offs?)\b/i;

const TIERS = {
  simple: { minSources: 3, topK: 3 },
  medium: { minSources: 5, topK: 5 },
  complex: { minSources: 8, topK: 15 },
  research: { minSources: 10, topK: 20 },
};

export function classifyComplexity(query) {
  const trimmed = (query || '').trim();
  const wordCount = trimmed.split(/\s+/).filter(Boolean).length;
  const questionMarks = (trimmed.match(/\?/g) || []).length;

  if (RESEARCH_KEYWORDS.test(trimmed) || wordCount > 60) return 'research';
  if (COMPLEX_KEYWORDS.test(trimmed) || wordCount > 25 || questionMarks > 1) return 'complex';
  if (wordCount > 10) return 'medium';
  return 'simple';
}

export function tierFor(query) {
  return TIERS[classifyComplexity(query)];
}
