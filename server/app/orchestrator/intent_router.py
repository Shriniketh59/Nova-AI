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

# Simple arithmetic / calculator-style queries — these need no retrieval,
# no memory lookup, no web search: just the model (or a calculator) doing
# math directly. Keeps trivial queries off the full agent pipeline.
MATH_RE = re.compile(
    r"^\s*(what\s+is\s+|calculate\s+|compute\s+|solve\s+)?"
    r"[\d\.\s]+[\+\-\*/x×÷\^%][\d\.\s\+\-\*/x×÷\^%\(\)]*\s*\??\s*$",
    re.I,
)

GREETING_RE = re.compile(
    r"^\s*(hi|hello|hey|yo|sup|hii+|good\s+(morning|evening|afternoon|night))(\s+(there|nova|assistant|bot|friend|all|everyone))?\W*$",
    re.I,
)

# Political/public-office/organizational titles whose holder can change at any
# time — a question about "who currently holds X" is never safe to answer
# from model memory alone, even without an explicit "current"/"latest" cue.
OFFICE_TITLES = (
    r"ceo|cfo|coo|cto|chairman|chairperson|chair|leader|president|vice\s+president|"
    r"vp|pm|prime\s+minister|cm|chief\s+minister|governor|mayor|senator|"
    r"congress(wo)?man|mp|minister|secretary(\s+general)?|speaker|chancellor|"
    r"monarch|king|queen|emperor|pope|premier|director\s+general|head\s+of\s+state|"
    r"head\s+coach|coach|captain|commissioner|superintendent|principal|dean|"
    r"ambassador|attorney\s+general|chief\s+justice"
)

# Questions that require live/current information from the web
CURRENT_INFO_RE = re.compile(
    r"\b(latest|current(ly)?|today|right\s+now|this\s+(week|month|year)|"
    r"recent(ly)?|up[-\s]to[-\s]date|as\s+of\s+(now|today)|breaking\s+news|"
    r"live\s+score|stock\s+price|exchange\s+rate|weather|"
    r"who\s+(is|was|are|were|'s)\s+(the\s+)?(current|new|" + OFFICE_TITLES + r")\b(\s+of\b)?|"
    r"who\s+(is|are)\s+(the\s+)?(current|new)\b|"
    r"who\s+won\s+(the\s+)?(election|championship|award|match|game|series|title|race|contest|primary|nomination)|"
    r"election\s+(result|winner|outcome)s?|"
    r"(won|winner\s+of)\s+the\s+(20\d{2}\s+)?election|"
    r"when\s+(did|was|is|will)\s+.{0,60}?"
    r"(happen|occur|start|end|begin|resign|step\s+down|retire|die|pass(ed)?\s+away|"
    r"elected|appointed|sworn\s+in|inaugurated|announced|release[ds]?|launch(ed)?)\b|"
    r"how\s+long\s+has\s+.{0,40}?\bbeen\b|"
    r"since\s+when\s+(is|has|was)|"
    r"still\s+(the\s+)?(" + OFFICE_TITLES + r")|"
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
    from ..utils.query_regularizer import regularize_query
    q = (query or "").strip()
    reg = regularize_query(q)
    q_norm = reg["normalized_query"]

    # Check greeting on original and normalized
    if GREETING_RE.match(q) or GREETING_RE.match(q_norm):
        return "greeting"

    if MATH_RE.match(q) or MATH_RE.match(q_norm):
        return "math"

    if is_coding_question(q) or is_coding_question(q_norm):
        return "coding"

    if CURRENT_INFO_RE.search(q) or CURRENT_INFO_RE.search(q_norm):
        return "current_info"

    # Only trigger doc_query if there's something in the KB/chat to retrieve
    if (has_files or has_kb_docs) and (DOC_TRIGGER_RE.search(q) or DOC_TRIGGER_RE.search(q_norm)):
        return "doc_query"

    # Long questions with local files → likely doc query
    if has_files and len(q.split()) > 4:
        return "doc_query"

    return "general"


def is_coding_question(query: str) -> bool:
    from ..utils.query_regularizer import regularize_query
    q = (query or "").strip()
    q_norm = regularize_query(q)["normalized_query"]

    for candidate in (q, q_norm):
        if CODE_DOMAIN_RE.search(candidate):
            return True
        if CODE_LANGS_RE.search(candidate) and CODE_NOUNS_RE.search(candidate):
            return True
        if bool(CODE_VERBS_RE.search(candidate) and (CODE_NOUNS_RE.search(candidate) or CODE_LANGS_RE.search(candidate))):
            return True
    return False


def needs_web_search(intent: str) -> bool:
    # Only "current_info" queries need a live web search. Doc/knowledge
    # ("doc_query") and general questions are served from the vector DB /
    # model directly — hitting DDGS for every general query added latency
    # and unrelated web noise for no benefit.
    return intent == "current_info"


def needs_vector_retrieval(intent: str, has_files: bool = False, has_kb_docs: bool = False) -> bool:
    if intent in ("greeting", "coding"):
        return False
    if intent == "doc_query":
        return True
    if has_files or has_kb_docs:
        return intent == "general"
    return False
