import re

RESEARCH_KEYWORDS = re.compile(
    r"\b(research|in depth|comprehensive|thorough|literature|survey of|state of the art)\b", re.I
)
COMPLEX_KEYWORDS = re.compile(
    r"\b(compare|comparison|vs\.?|versus|difference between|pros and cons|analyze|analyse|evaluate|trade-?offs?)\b",
    re.I,
)

TIERS = {
    "simple": {"minSources": 3, "topK": 5},
    "medium": {"minSources": 5, "topK": 8},
    "complex": {"minSources": 8, "topK": 12},
    "research": {"minSources": 10, "topK": 15},
}


def classify_complexity(query: str) -> str:
    trimmed = (query or "").strip()
    word_count = len([w for w in trimmed.split() if w])
    question_marks = trimmed.count("?")

    if RESEARCH_KEYWORDS.search(trimmed) or word_count > 60:
        return "research"
    if COMPLEX_KEYWORDS.search(trimmed) or word_count > 25 or question_marks > 1:
        return "complex"
    if word_count > 10:
        return "medium"
    return "simple"


def tier_for(query: str) -> dict:
    return TIERS[classify_complexity(query)]
