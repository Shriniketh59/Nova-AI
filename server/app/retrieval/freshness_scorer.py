import math
import re
from datetime import datetime, timezone
from typing import List
from urllib.parse import urlparse

OFFICIAL_SUFFIXES = (".gov", ".edu", ".mil", ".org")
OFFICIAL_DOMAINS = {
    "who.int", "un.org", "europa.eu", "nasa.gov", "nih.gov", "cdc.gov",
    "sec.gov", "irs.gov", "arxiv.org", "dl.acm.org", "ieee.org",
}
REFERENCE_DOMAINS = {"wikipedia.org", "britannica.com", "docs.python.org", "developer.mozilla.org"}
NEWS_DOMAINS = {"reuters.com", "apnews.com", "bbc.com", "nytimes.com", "theguardian.com"}


def parse_date(date_val: str | None) -> datetime | None:
    if not date_val:
        return None
    try:
        clean = date_val.replace("Z", "+00:00")
        return datetime.fromisoformat(clean)
    except Exception:
        pass
    # Try regex search for YYYY-MM-DD or YYYY
    m = re.search(r"\b(20\d{2})[-/](0[1-9]|1[0-2])[-/](0[1-9]|[12]\d|3[01])\b", str(date_val))
    if m:
        try:
            return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)), tzinfo=timezone.utc)
        except Exception:
            pass
    m_year = re.search(r"\b(20\d{2})\b", str(date_val))
    if m_year:
        return datetime(int(m_year.group(1)), 1, 1, tzinfo=timezone.utc)
    return None


def calculate_freshness(date_val: str | None, half_life_days: float = 60.0) -> float:
    """Calculates exponential freshness decay score between 0.05 and 1.0."""
    dt = parse_date(date_val)
    if not dt:
        return 0.5  # Neutral default for undated content

    now = datetime.now(timezone.utc)
    age_seconds = max(0.0, (now - dt).total_seconds())
    age_days = age_seconds / 86400.0

    # Half-life decay: score drops to 0.5 after half_life_days
    decay_rate = math.log(2) / max(1.0, half_life_days)
    score = math.exp(-decay_rate * age_days)
    return max(0.05, min(1.0, round(score, 4)))


def calculate_authority(item: dict) -> float:
    """Computes source authority score between 0.2 and 1.0 based on origin domain/type."""
    source_type = item.get("source_type", item.get("type", "file"))
    if source_type in ("file", "document", "upload"):
        # Uploaded knowledge base documents have high authority for the user
        return 0.85

    url = item.get("source_url") or item.get("url") or ""
    if not url:
        return 0.5

    try:
        host = urlparse(url).hostname or url
        if host.startswith("www."):
            host = host[4:]
        host = host.lower()
    except Exception:
        return 0.5

    if host in OFFICIAL_DOMAINS or any(host.endswith(suf) for suf in OFFICIAL_SUFFIXES):
        return 0.95
    if host in REFERENCE_DOMAINS:
        return 0.85
    if host in NEWS_DOMAINS:
        return 0.80
    return 0.60


def compute_composite_score(
    semantic_score: float,
    lexical_score: float,
    freshness_score: float,
    authority_score: float,
    intent: str = "general",
) -> float:
    """Computes weighted composite score dynamically tuned by query intent."""
    # Normalize inputs to [0, 1]
    sem = max(0.0, min(1.0, semantic_score))
    lex = max(0.0, min(1.0, lexical_score))
    fresh = max(0.0, min(1.0, freshness_score))
    auth = max(0.0, min(1.0, authority_score))

    if intent == "current_info":
        # Time-sensitive: freshness and authority carry significant weight
        w_sem = 0.35
        w_lex = 0.20
        w_fresh = 0.35
        w_auth = 0.10
    elif intent in ("research", "factual"):
        # Factual/research: semantic relevance and authority take precedence
        w_sem = 0.45
        w_lex = 0.25
        w_fresh = 0.15
        w_auth = 0.15
    else:
        # General balanced default
        w_sem = 0.50
        w_lex = 0.25
        w_fresh = 0.15
        w_auth = 0.10

    total = (w_sem * sem) + (w_lex * lex) + (w_fresh * fresh) + (w_auth * auth)
    return round(total, 4)


def rank_candidates_with_freshness(candidates: List[dict], intent: str = "general") -> List[dict]:
    """Applies freshness scoring, authority scoring, and composite ranking to candidates."""
    scored = []
    for c in candidates:
        sem_score = c.get("similarity", 0.0)
        lex_score = min(1.0, c.get("keywordScore", 0.0))
        if "hybridScore" in c and sem_score == 0:
            sem_score = min(1.0, c["hybridScore"] * 25.0)

        date_val = c.get("published_at") or c.get("updated_at") or c.get("created_at")
        freshness = c.get("freshness_score") or calculate_freshness(date_val)
        authority = c.get("authority_score") or calculate_authority(c)

        final_score = compute_composite_score(
            semantic_score=sem_score,
            lexical_score=lex_score,
            freshness_score=freshness,
            authority_score=authority,
            intent=intent,
        )

        scored.append({
            **c,
            "freshness_score": freshness,
            "authority_score": authority,
            "composite_score": final_score,
        })

    scored.sort(key=lambda x: x["composite_score"], reverse=True)
    return scored
