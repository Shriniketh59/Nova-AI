"""
Intent Router — lightweight regex-based classifier.

Determines what the local orchestrator should do with an input query WITHOUT
making any LLM call (keeps the common path fast).

Intents:
  greeting    → no retrieval, short reply
  coding      → route to CodeAgent
  current_info → DDGS web search required
  doc_query   → Vector DB retrieval relevant
  general     → try Vector DB first, then Llama with no context
"""
import re

# ---------------------------------------------------------------------------
# Pattern definitions
# ---------------------------------------------------------------------------

GREETING_RE = re.compile(
    r"^\s*(hi|hello|hey|yo|sup|hii+|good\s+(morning|evening|afternoon|night))(\s+(there|nova|assistant|bot|friend|all|everyone))?\W*$",
    re.I,
)

# Questions that require live/current information from the web
CURRENT_INFO_RE = re.compile(
    r"\b(latest|current(ly)?|today|right\s+now|this\s+(week|month|year)|"
    r"recent(ly)?|up[-\s]to[-\s]date|as\s+of\s+(now|today)|breaking\s+news|"
    r"live\s+score|stock\s+price|exchange\s+rate|weather|"
    r"who\s+is\s+the\s+(current|new|ceo|leader|president|cm|chief\s+minister)|"
    r"20(2[4-9]|3\d))\b",
    re.I,
)

# Coding intent — language + action signal
CODE_LANGS_RE = re.compile(
    r"\b(java|python|javascript|typescript|c\+\+|c#|go|golang|rust|ruby|php|"
    r"sql|html|css|kotlin|swift|react|node\.?js|express)\b",
    re.I,
)
CODE_VERBS_RE = re.compile(
    r"\b(write|give|generate|create|implement|build|code|fix|debug|refactor|"
    r"optimize|optimise|explain\s+code|review\s+code)\b",
    re.I,
)
CODE_NOUNS_RE = re.compile(
    r"\b(code|function|algorithm|script|program|snippet|class|component|"
    r"endpoint|api|query|regex|method|interface|struct)\b",
    re.I,
)
CODE_DOMAIN_RE = re.compile(
    r"\b(leetcode|dsa|data\s+structure|hackerrank|codeforces|merge\s+sort|"
    r"quick\s+sort|binary\s+search|two\s+sum|fibonacci|dynamic\s+programming)\b",
    re.I,
)

# Document/knowledge queries that should trigger Vector DB lookup
DOC_TRIGGER_RE = re.compile(
    r"\b(document|uploaded|attachment|file|pdf|report|resume|cv|specification|"
    r"contract|explain|summarize|summarise|analyze|analyse|what\s+does|"
    r"according\s+to)\b",
    re.I,
)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def classify_intent(query: str, has_files: bool = False, has_kb_docs: bool = False) -> str:
    """
    Returns one of: 'greeting', 'coding', 'current_info', 'doc_query', 'general'

    Parameters
    ----------
    query        : raw user query text
    has_files    : True if there are uploaded files in the current chat
    has_kb_docs  : True if the knowledge base (Vector DB) has any documents
    """
    q = (query or "").strip()

    if GREETING_RE.match(q):
        return "greeting"

    if is_coding_question(q):
        return "coding"

    if CURRENT_INFO_RE.search(q):
        return "current_info"

    # Only trigger doc_query if there's something in the KB/chat to retrieve
    if (has_files or has_kb_docs) and DOC_TRIGGER_RE.search(q):
        return "doc_query"

    # Long questions with local files → likely doc query
    if has_files and len(q.split()) > 4:
        return "doc_query"

    return "general"


def is_coding_question(query: str) -> bool:
    if CODE_DOMAIN_RE.search(query):
        return True
    if CODE_LANGS_RE.search(query) and CODE_NOUNS_RE.search(query):
        return True
    return bool(CODE_VERBS_RE.search(query) and (CODE_NOUNS_RE.search(query) or CODE_LANGS_RE.search(query)))


def needs_web_search(intent: str) -> bool:
    return intent != "greeting"


def needs_vector_retrieval(intent: str) -> bool:
    return intent in ("doc_query", "general")
