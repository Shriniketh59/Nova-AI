import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import List, Set

CURRENT_YEAR = datetime.now(timezone.utc).year

GREETING_RE = re.compile(
    r"^\s*(hi|hello|hey|yo|sup|hii+|hello+|good (morning|evening|afternoon)|howdy|greetings)\W*$",
    re.I,
)

CURRENT_INFO_RE = re.compile(
    r"\b(latest|current(ly)?|today|right now|this (week|month|year)|"
    r"recent(ly)?|up[- ]to[- ]date|as of (now|today)|breaking news|"
    r"live score|stock price|exchange rate|who is the (current|new|now)|"
    rf"20(2[4-9]|3\d)|{CURRENT_YEAR})\b",
    re.I,
)

RESEARCH_RE = re.compile(
    r"\b(explain|compare|comparison|research|analy[sz]e|analysis|in[- ]depth|"
    r"deep dive|comprehensive|thorough|survey|literature review|overview of|"
    r"state of the art|pros and cons|trade-?offs?|history of|evaluate|investigate)\b",
    re.I,
)

CODING_RE = re.compile(
    r"\b(function|def |class |import |async |const |let |python|javascript|"
    r"typescript|sql|docker|algorithm|bug|error|stack trace|syntax|refactor)\b",
    re.I,
)

STOPWORDS: Set[str] = {
    "the", "a", "an", "is", "are", "was", "were", "of", "to", "in", "on", "for",
    "and", "or", "with", "what", "how", "do", "does", "i", "can", "you", "tell", "me",
    "about", "give", "please", "my", "we", "at", "by", "from", "be", "this", "that",
}

ENTITY_RE = re.compile(r"\b[A-Z][a-zA-Z0-9_-]+(?:\s+[A-Z][a-zA-Z0-9_-]+)*\b")
QUOTED_RE = re.compile(r'["\']([^"\']+)["\']')


@dataclass
class QueryAnalysis:
    original_query: str
    normalized_query: str
    intent: str  # greeting, current_info, research, coding, factual, general
    is_greeting: bool
    requires_fresh_web: bool
    is_research: bool
    is_coding: bool
    entities: List[str] = field(default_factory=list)
    keywords: List[str] = field(default_factory=list)
    retrieval_queries: List[str] = field(default_factory=list)
    sources: dict = field(default_factory=dict)  # {"dense": bool, "sparse": bool, "web": bool}


def normalize_query(query: str) -> str:
    """Normalizes whitespace, casing, and basic punctuation."""
    if not query:
        return ""
    q = re.sub(r"[ \t\r\n]+", " ", query).strip()
    return q


def extract_keywords(query: str) -> List[str]:
    tokens = re.findall(r"[a-zA-Z0-9]+", query.lower())
    return [t for t in tokens if t not in STOPWORDS and len(t) > 1]


def extract_entities(query: str) -> List[str]:
    quoted = QUOTED_RE.findall(query)
    capitalized = ENTITY_RE.findall(query)
    merged = []
    seen = set()
    for item in [*quoted, *capitalized]:
        clean = item.strip()
        if clean and clean.lower() not in seen and clean.lower() not in STOPWORDS:
            seen.add(clean.lower())
            merged.append(clean)
    return merged


def analyze_query(query: str, has_attached_files: bool = False) -> QueryAnalysis:
    norm = normalize_query(query)

    is_greeting = bool(GREETING_RE.match(norm))
    if is_greeting:
        return QueryAnalysis(
            original_query=query,
            normalized_query=norm,
            intent="greeting",
            is_greeting=True,
            requires_fresh_web=False,
            is_research=False,
            is_coding=False,
            entities=[],
            keywords=[],
            retrieval_queries=[],
            sources={"dense": False, "sparse": False, "web": False},
        )

    is_current = bool(CURRENT_INFO_RE.search(norm))
    is_research = bool(RESEARCH_RE.search(norm))
    is_coding = bool(CODING_RE.search(norm))

    if is_current:
        intent = "current_info"
    elif is_research:
        intent = "research"
    elif is_coding:
        intent = "coding"
    elif len(norm.split()) <= 6 and ("what" in norm.lower() or "who" in norm.lower() or "when" in norm.lower()):
        intent = "factual"
    else:
        intent = "general"

    entities = extract_entities(query)
    keywords = extract_keywords(norm)

    # Build retrieval query variants fast without blocking LLM call
    retrieval_queries = [norm]
    if is_research and entities:
        entity_str = " ".join(entities[:2])
        if entity_str.lower() not in norm.lower() or len(norm) > len(entity_str) + 15:
            retrieval_queries.append(f"{entity_str} overview architecture")
    elif is_current and not has_attached_files:
        # Append temporal anchor if not present
        if str(CURRENT_YEAR) not in norm:
            retrieval_queries.append(f"{norm} {CURRENT_YEAR}")

    # Decide retrieval sources
    # Dense & Sparse run if not purely greeting
    # Web runs if:
    # 1. Query is current info, OR
    # 2. No attached files in the chat (general research), OR
    # 3. Research query wanting broad evidence
    requires_fresh_web = is_current or (not has_attached_files and intent != "coding")
    sources = {
        "dense": True,
        "sparse": True,
        "web": requires_fresh_web,
    }

    return QueryAnalysis(
        original_query=query,
        normalized_query=norm,
        intent=intent,
        is_greeting=False,
        requires_fresh_web=requires_fresh_web,
        is_research=is_research,
        is_coding=is_coding,
        entities=entities,
        keywords=keywords,
        retrieval_queries=retrieval_queries[:3],
        sources=sources,
    )
