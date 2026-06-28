// Cheap regex-based router, no LLM call — decides BEFORE any retrieval/web
// search which agent handles this turn. Priority order enforced here:
// Uploaded Image > Uploaded Document > Coding > Memory/RAG > Web Search. If
// an image or document is attached, web-search-enabled general path must
// never run.
const RESUME_RE = /\bresume\b|\bcv\b/i;
const ATS_RE = /\bats\b.*(score|calculate|rate)|calculate.*\bats\b/i;
const ANALYZE_RE = /\b(review|analyze|analyse|summarize|summarise|check|evaluate|critique)\b/i;
const COMPARE_RE = /\b(compare|comparison|diff|difference|differences|contrast)\b.*\b(document|doc|file|pdf|these|them|both)\b|\b(document|doc|file)s?\b.*\b(compare|differ|contrast)\b/i;

// Coding questions skip the whole research->plan->review pipeline (RAG,
// web search, multi-source evidence) — none of that helps "write a
// mergesort in Python", it only adds 1-3min of latency for zero benefit.
// Matches explicit language/task asks ("write java code", "python
// function", "leetcode", "sql query", "react component") rather than every
// mention of a language name, to avoid false-positiving on "what is Python
// used for" (a factual question, not a code-gen request).
const CODE_LANGS = /(java|python|javascript|typescript|c\+\+|c#|go|golang|rust|ruby|php|sql|html|css|kotlin|swift|react|node\.?js|express)/i;
const CODE_VERBS = /\b(write|give|generate|create|implement|build|code|fix|debug|refactor|optimi[sz]e)\b/i;
const CODE_NOUNS = /\b(code|function|algorithm|script|program|snippet|class|component|endpoint|api|query|regex)\b/i;
const CODE_DOMAIN_RE = /\b(leetcode|dsa|data structure|hackerrank|codeforces|merge sort|quick sort|binary search|two sum|fibonacci)\b/i;

export function isCodingQuestion(query) {
  if (CODE_DOMAIN_RE.test(query)) return true;
  return CODE_VERBS.test(query) && (CODE_NOUNS.test(query) || CODE_LANGS.test(query));
}

export function classifyTask(query, { hasFiles, hasImages, fileCount = 0 } = {}) {
  if (hasImages) return { type: 'vision' };
  if (!hasFiles && isCodingQuestion(query)) return { type: 'coding' };
  if (!hasFiles) return { type: 'general' };

  if (fileCount >= 2 && COMPARE_RE.test(query)) return { type: 'document_comparison' };
  if (ATS_RE.test(query)) return { type: 'ats' };
  if (RESUME_RE.test(query) && ANALYZE_RE.test(query)) return { type: 'resume_analysis' };
  if (ANALYZE_RE.test(query)) return { type: 'document_analysis' };
  if (isCodingQuestion(query)) return { type: 'coding' };

  return { type: 'general' };
}
