from urllib.parse import urlparse

OFFICIAL_SUFFIXES = [".gov", ".edu", ".mil"]
OFFICIAL_DOMAINS = {
    "who.int", "un.org", "europa.eu", "nasa.gov", "nih.gov", "cdc.gov",
    "sec.gov", "irs.gov", "supremecourt.gov",
}
REFERENCE_DOMAINS = {"wikipedia.org", "britannica.com"}
COMMUNITY_DOMAINS = {
    "stackoverflow.com", "github.com", "developer.mozilla.org", "docs.python.org",
    "nodejs.org", "reactjs.org", "react.dev", "npmjs.com", "reuters.com",
    "apnews.com", "bbc.com", "bbc.co.uk", "nytimes.com",
}

TIER_RANK = {"official": 0, "reference": 1, "community": 2, "unknown": 3}


def extract_hostname(url: str):
    try:
        hostname = urlparse(url).hostname
        if not hostname:
            return None
        return hostname[4:] if hostname.startswith("www.") else hostname
    except Exception:
        return None


def _matches_domain_set(hostname: str, domain_set: set) -> bool:
    return any(hostname == d or hostname.endswith(f".{d}") for d in domain_set)


def classify_domain(url: str) -> str:
    hostname = extract_hostname(url)
    if not hostname:
        return "unknown"

    if _matches_domain_set(hostname, OFFICIAL_DOMAINS) or any(hostname.endswith(suf) for suf in OFFICIAL_SUFFIXES):
        return "official"
    if _matches_domain_set(hostname, REFERENCE_DOMAINS):
        return "reference"
    if _matches_domain_set(hostname, COMMUNITY_DOMAINS):
        return "community"
    return "unknown"


def rank_sources(sources: list[dict]) -> list[dict]:
    """Attaches trustTier to each web source and resorts so higher-trust
    sources come first among results of similar relevance."""
    ranked = [{**s, "trustTier": classify_domain(s["url"]), "_originalRank": i} for i, s in enumerate(sources)]

    def cmp_key(item):
        return item

    import functools

    def comparator(a, b):
        tier_diff = TIER_RANK[a["trustTier"]] - TIER_RANK[b["trustTier"]]
        if tier_diff != 0 and abs(a["_originalRank"] - b["_originalRank"]) <= 2:
            return tier_diff
        return a["_originalRank"] - b["_originalRank"]

    ranked.sort(key=functools.cmp_to_key(comparator))
    return [{k: v for k, v in s.items() if k != "_originalRank"} for s in ranked]


def count_trust_tiers(sources: list[dict]) -> dict:
    counts = {"official": 0, "reference": 0, "community": 0, "unknown": 0}
    for s in sources:
        tier = s.get("trustTier")
        if tier in counts:
            counts[tier] += 1
    return counts
