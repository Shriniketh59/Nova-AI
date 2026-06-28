// Domain trust tiers for web search results. Never used to override
// relevance ranking outright — only to (a) tie-break within similar
// relevance, and (b) gate whether a contested-fact category (biography,
// politics, medical, legal, finance, news) can be answered with "high"
// confidence: see confidenceEngine.js's trustTiers param.
const OFFICIAL_SUFFIXES = ['.gov', '.edu', '.mil'];
const OFFICIAL_DOMAINS = new Set([
  'who.int', 'un.org', 'europa.eu', 'nasa.gov', 'nih.gov', 'cdc.gov',
  'sec.gov', 'irs.gov', 'supremecourt.gov'
]);
const REFERENCE_DOMAINS = new Set(['wikipedia.org', 'britannica.com']);
const COMMUNITY_DOMAINS = new Set([
  'stackoverflow.com', 'github.com', 'developer.mozilla.org', 'docs.python.org',
  'nodejs.org', 'reactjs.org', 'react.dev', 'npmjs.com', 'reuters.com',
  'apnews.com', 'bbc.com', 'bbc.co.uk', 'nytimes.com'
]);

export function extractHostname(url) {
  try {
    return new URL(url).hostname.replace(/^www\./, '').toLowerCase();
  } catch {
    return null;
  }
}

// Tiers, highest trust first: official > reference > community > unknown.
// "reference" (Wikipedia et al.) is deliberately below official — good for
// background, never the sole source for a contested fact per the brief.
// Matches the hostname itself or any subdomain (en.wikipedia.org should
// match wikipedia.org) without matching unrelated domains that merely
// contain the same substring (notwikipedia.org should not match).
function matchesDomainSet(hostname, domainSet) {
  return [...domainSet].some(d => hostname === d || hostname.endsWith(`.${d}`));
}

export function classifyDomain(url) {
  const hostname = extractHostname(url);
  if (!hostname) return 'unknown';

  if (matchesDomainSet(hostname, OFFICIAL_DOMAINS) || OFFICIAL_SUFFIXES.some(suf => hostname.endsWith(suf))) {
    return 'official';
  }
  if (matchesDomainSet(hostname, REFERENCE_DOMAINS)) return 'reference';
  if (matchesDomainSet(hostname, COMMUNITY_DOMAINS)) return 'community';
  return 'unknown';
}

// Attaches trustTier to each web source and resorts so higher-trust sources
// come first among results of similar relevance — relevance ordering from
// the search API is preserved as the primary key, trust only breaks ties
// within it (a clearly more relevant unknown-tier result still outranks a
// barely-relevant official one).
export function rankSources(sources) {
  const TIER_RANK = { official: 0, reference: 1, community: 2, unknown: 3 };
  return sources
    .map((s, i) => ({ ...s, trustTier: classifyDomain(s.url), _originalRank: i }))
    .sort((a, b) => {
      const tierDiff = TIER_RANK[a.trustTier] - TIER_RANK[b.trustTier];
      if (Math.abs(tierDiff) > 0 && Math.abs(a._originalRank - b._originalRank) <= 2) return tierDiff;
      return a._originalRank - b._originalRank;
    })
    .map(({ _originalRank, ...s }) => s);
}

export function countTrustTiers(sources) {
  const counts = { official: 0, reference: 0, community: 0, unknown: 0 };
  for (const s of sources) {
    if (s.trustTier && counts[s.trustTier] !== undefined) counts[s.trustTier]++;
  }
  return counts;
}
