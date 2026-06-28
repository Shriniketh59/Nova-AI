// Categories where stating a wrong fact is the exact failure mode this
// engine exists to prevent — these require official/reference backing
// before "high" confidence is allowed, regardless of raw source count.
const CONTESTED_FACT_CATEGORIES = new Set(['biography', 'politics', 'medical', 'legal', 'finance', 'news']);

// Answer Confidence — user-facing, distinct from retrieval/match score.
// Retrieval score (cosine similarity) measures search relevance, not answer
// reliability. This combines source count, agreement, coverage, contradictions,
// and (for contested-fact categories) whether any source is actually trustworthy.
export function computeAnswerConfidence({ sourceCount = 0, contradictions = [], docConfidence = null, hasWebSources = false, trustTiers = null, category = 'general' }) {
  if (sourceCount === 0) {
    return { score: 0, label: 'low', reason: 'No supporting sources found.' };
  }

  let score = 30; // base for having at least one source
  score += Math.min(sourceCount, 6) * 8; // up to +48 for source count
  if (docConfidence && docConfidence.label === 'high') score += 10;
  if (hasWebSources) score += 5;
  score -= contradictions.length * 20;

  const isContested = CONTESTED_FACT_CATEGORIES.has(category);
  const hasTrustedSource = trustTiers && (trustTiers.official > 0 || trustTiers.reference > 0);
  if (isContested && !hasTrustedSource) {
    // Cap below "high" regardless of source count — lots of low-trust
    // agreement still isn't grounds for confidently stating a contested fact.
    score = Math.min(score, 65);
  }

  score = Math.max(0, Math.min(100, score));
  const label = score >= 70 ? 'high' : score >= 30 ? 'medium' : 'low';

  let reason;
  if (contradictions.length > 0) {
    reason = `${contradictions.length} source conflict(s) detected — sources disagree on a specific fact.`;
  } else if (isContested && hasTrustedSource) {
    reason = 'Supported by official or reference sources.';
  } else if (isContested && !hasTrustedSource) {
    reason = 'No official or reference sources found for this claim — only community/blog sources available.';
  } else {
    reason = `${sourceCount} supporting source(s) found.`;
  }

  return { score, label, reason };
}
