import re

RESUME_RE = re.compile(r"\bresume\b|\bcv\b", re.I)
ATS_RE = re.compile(r"\bats\b.*(score|calculate|rate)|calculate.*\bats\b", re.I)
ANALYZE_RE = re.compile(r"\b(review|analyze|analyse|summarize|summarise|check|evaluate|critique)\b", re.I)
COMPARE_RE = re.compile(
    r"\b(compare|comparison|diff|difference|differences|contrast)\b.*\b(document|doc|file|pdf|these|them|both)\b"
    r"|\b(document|doc|file)s?\b.*\b(compare|differ|contrast)\b",
    re.I,
)

CODE_LANGS = re.compile(
    r"(java|python|javascript|typescript|c\+\+|c#|go|golang|rust|ruby|php|sql|html|css|kotlin|swift|react|node\.?js|express)",
    re.I,
)
CODE_VERBS = re.compile(r"\b(write|give|generate|create|implement|build|code|fix|debug|refactor|optimi[sz]e)\b", re.I)
CODE_NOUNS = re.compile(r"\b(code|function|algorithm|script|program|snippet|class|component|endpoint|api|query|regex)\b", re.I)
CODE_DOMAIN_RE = re.compile(
    r"\b(leetcode|dsa|data structure|hackerrank|codeforces|merge sort|quick sort|binary search|two sum|fibonacci)\b",
    re.I,
)


def is_coding_question(query: str) -> bool:
    if CODE_DOMAIN_RE.search(query):
        return True
    return bool(CODE_VERBS.search(query) and (CODE_NOUNS.search(query) or CODE_LANGS.search(query)))


RESEARCH_RE = re.compile(r"\b(research|in depth|comprehensive|thorough|literature|survey of|state of the art)\b", re.I)
BIOGRAPHY_RE = re.compile(r"\bwho (is|was)\b|\bbiography\b|\bborn (in|on)\b|\blife of\b", re.I)
NEWS_RE = re.compile(r"\b(latest|breaking|today'?s|this week'?s|recent)\b.*\b(news|update|event)s?\b|\bwhat'?s happening\b", re.I)
MATH_RE = re.compile(r"\b(solve|calculate|compute)\b.*\b(equation|integral|derivative|matrix|sum|expression)\b|[0-9]+\s*[-+*/^]\s*[0-9]+", re.I)
MEDICAL_RE = re.compile(r"\b(symptom|diagnos|disease|medication|dosage|treatment|patient|clinical)\w*\b", re.I)
LEGAL_RE = re.compile(r"\b(contract|statute|lawsuit|liability|plaintiff|defendant|clause|jurisdiction|legal(ly)?)\b", re.I)


def classify_topic(query: str) -> str:
    """Lightweight heuristic topic-type classifier (keyword/regex based).

    Distinct from `classify_task`, which decides *which agent handles this
    turn* (vision/coding/document_*). This decides the *subject-matter
    category* of a query — used for routing to research/biography/news/
    math/medical/legal specialists and for confidence scoring (contested
    categories in confidence_engine.py)."""
    q = query or ""
    if is_coding_question(q):
        return "coding"
    if MATH_RE.search(q):
        return "math"
    if MEDICAL_RE.search(q):
        return "medical"
    if LEGAL_RE.search(q):
        return "legal"
    if BIOGRAPHY_RE.search(q):
        return "biography"
    if NEWS_RE.search(q):
        return "news"
    if RESEARCH_RE.search(q):
        return "research"
    return "chat"


def classify_task(query: str, has_files: bool = False, has_images: bool = False, file_count: int = 0) -> dict:
    """Priority order: Uploaded Image > Uploaded Document > Coding > Memory/RAG > Web Search."""
    if has_images:
        return {"type": "vision"}
    if not has_files and is_coding_question(query):
        return {"type": "coding"}
    if not has_files:
        return {"type": "general"}

    if file_count >= 2 and COMPARE_RE.search(query):
        return {"type": "document_comparison"}
    if ATS_RE.search(query):
        return {"type": "ats"}
    if RESUME_RE.search(query) and ANALYZE_RE.search(query):
        return {"type": "resume_analysis"}
    if ANALYZE_RE.search(query):
        return {"type": "document_analysis"}
    if is_coding_question(query):
        return {"type": "coding"}

    return {"type": "general"}
