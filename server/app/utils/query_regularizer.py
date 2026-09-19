"""
Query Regularizer — normalization and spelling mistake tolerance module.

Ensures that user queries with typographical errors, phonetic misspellings,
or grammatical slips are accurately interpreted across:
1. Intent classification (IntentRouter)
2. Keyword / BM25 search (KeywordSearch)
3. Memory lookups (MemoryAgent)
4. Context continuation / follow-up detection (ContextFilter)
5. Orchestration and LLM prompt grounding
"""
import re
from typing import Dict, List, Set, Tuple

# Static high-confidence typo dictionary for common technical, conversational,
# programming, and query-intent terms.
TYPO_DICTIONARY: Dict[str, str] = {
    # Programming languages & tools
    "pythn": "python",
    "pyhton": "python",
    "pytn": "python",
    "pyton": "python",
    "jva": "java",
    "jaav": "java",
    "javascrip": "javascript",
    "javscript": "javascript",
    "javascrpt": "javascript",
    "typscript": "typescript",
    "typwscript": "typescript",
    "typescrpt": "typescript",
    "cplusplus": "c++",
    "cpluplus": "c++",
    "csharpe": "c#",
    "csharp": "c#",
    "golan": "golang",
    "rubby": "ruby",
    "sqll": "sql",
    "htmll": "html",
    "htm": "html",
    "csss": "css",
    "kotln": "kotlin",
    "reac": "react",
    "reack": "react",
    "docer": "docker",
    "dockr": "docker",
    "kubernets": "kubernetes",
    "kubenetes": "kubernetes",
    "kubernetees": "kubernetes",

    # Common programming nouns & algorithms
    "algorthm": "algorithm",
    "algoritm": "algorithm",
    "algortihm": "algorithm",
    "algorithem": "algorithm",
    "binnary": "binary",
    "binery": "binary",
    "binari": "binary",
    "serch": "search",
    "seach": "search",
    "saerch": "search",
    "functon": "function",
    "funtion": "function",
    "funciton": "function",
    "programe": "program",
    "progrm": "program",
    "prgrm": "program",
    "progrma": "program",
    "snippit": "snippet",
    "snipt": "snippet",
    "datastructure": "data structure",
    "datastructures": "data structures",
    "recusion": "recursion",
    "recurson": "recursion",
    "itration": "iteration",
    "iterashun": "iteration",
    "dsa": "dsa",

    # Action verbs
    "writ": "write",
    "wite": "write",
    "wrtie": "write",
    "wrte": "write",
    "implment": "implement",
    "impliment": "implement",
    "imlement": "implement",
    "explin": "explain",
    "explan": "explain",
    "explane": "explain",
    "expalin": "explain",
    "sumarize": "summarize",
    "summarise": "summarize",
    "sumarise": "summarize",
    "sumerize": "summarize",
    "anlyze": "analyze",
    "analize": "analyze",
    "anlyse": "analyze",
    "debugg": "debug",
    "debu": "debug",
    "refactr": "refactor",
    "refacter": "refactor",
    "optmize": "optimize",
    "optimise": "optimize",
    "optmise": "optimize",
    "compil": "compile",
    "compyle": "compile",

    # Intent & question keywords
    "whast": "what",
    "wht": "what",
    "wat": "what",
    "wats": "what is",
    "whats": "what is",
    "whos": "who is",
    "whois": "who is",
    "currnt": "current",
    "cureent": "current",
    "curnt": "current",
    "curent": "current",
    "latst": "latest",
    "latets": "latest",
    "ltest": "latest",
    "todayy": "today",
    "tday": "today",
    "recnt": "recent",
    "receent": "recent",
    "presidnt": "president",
    "prezident": "president",
    "minstr": "minister",
    "minisiter": "minister",
    "karnatka": "karnataka",
    "karnatak": "karnataka",
    "bengaluru": "bengaluru",
    "banglore": "bangalore",
    "rember": "remember",
    "rememebr": "remember",
    "remmbr": "remember",
    "prefere": "prefer",
    "prefr": "prefer",
    "favorit": "favorite",
    "favrite": "favorite",
    "favourite": "favorite",
    "differnce": "difference",
    "diffrence": "difference",
    "compr": "compare",
    "compair": "compare",
    "modl": "model",
    "modls": "models",
    "lerning": "learning",
    "leran": "learn",
    "lrn": "learn",
    "artifical": "artificial",
    "inteligence": "intelligence",
    "intellegence": "intelligence",
}

_WORD_RE = re.compile(r"[a-zA-Z0-9+#\.\-]+")


def levenshtein_distance(s1: str, s2: str) -> int:
    """Computes Levenshtein edit distance between two strings."""
    if s1 == s2:
        return 0
    len1, len2 = len(s1), len(s2)
    if abs(len1 - len2) > 2:
        return abs(len1 - len2)

    dp = list(range(len2 + 1))
    for i, c1 in enumerate(s1):
        new_dp = [i + 1] * (len2 + 1)
        for j, c2 in enumerate(s2):
            cost = 0 if c1 == c2 else 1
            new_dp[j + 1] = min(
                dp[j + 1] + 1,      # deletion
                new_dp[j] + 1,      # insertion
                dp[j] + cost,       # substitution
            )
        dp = new_dp
    return dp[len2]


def regularize_query(query: str) -> dict:
    """
    Normalizes a query by correcting typos, normalizing whitespace,
    and identifying key semantic concepts.

    Returns:
        {
            "original_query": str,
            "normalized_query": str,
            "corrections": dict[str, str],
            "tokens": list[str],
            "normalized_tokens": list[str],
        }
    """
    if not query or not query.strip():
        return {
            "original_query": query or "",
            "normalized_query": query or "",
            "corrections": {},
            "tokens": [],
            "normalized_tokens": [],
        }

    raw = query.strip()
    words = _WORD_RE.findall(raw)
    corrections = {}
    normalized_words = []

    for word in words:
        w_lower = word.lower()
        if w_lower in TYPO_DICTIONARY:
            corrected = TYPO_DICTIONARY[w_lower]
            corrections[word] = corrected
            normalized_words.append(corrected)
        else:
            # Check if an edit distance of 1 matches any known keyword >= 4 chars
            matched_correction = None
            if len(w_lower) >= 4 and w_lower not in TYPO_DICTIONARY.values():
                for target in TYPO_DICTIONARY.values():
                    if abs(len(w_lower) - len(target)) <= 1:
                        if levenshtein_distance(w_lower, target) <= 1:
                            matched_correction = target
                            break
            if matched_correction:
                corrections[word] = matched_correction
                normalized_words.append(matched_correction)
            else:
                normalized_words.append(word)

    # Reconstruct normalized string preserving punctuation flow
    normalized_str = raw
    for orig, corr in corrections.items():
        # Match whole word boundary
        pattern = re.compile(r"\b" + re.escape(orig) + r"\b", re.IGNORECASE)
        normalized_str = pattern.sub(corr, normalized_str)

    # Normalize excessive internal spacing
    normalized_str = re.sub(r"\s+", " ", normalized_str).strip()

    return {
        "original_query": raw,
        "normalized_query": normalized_str,
        "corrections": corrections,
        "tokens": [w.lower() for w in words],
        "normalized_tokens": [w.lower() for w in normalized_words],
    }


def fuzzy_token_overlap(
    query_terms: Set[str],
    corpus_terms: Set[str],
    max_distance: int = 1,
) -> Set[str]:
    """
    Finds overlapping tokens between query and corpus, allowing an edit distance
    of up to max_distance for words with length >= 4.
    """
    exact_matches = query_terms & corpus_terms
    matched = set(exact_matches)

    unmatched_query = query_terms - matched
    unmatched_corpus = corpus_terms - matched

    for qt in unmatched_query:
        if len(qt) < 4:
            continue
        for ct in unmatched_corpus:
            if len(ct) < 4:
                continue
            if abs(len(qt) - len(ct)) <= max_distance:
                if levenshtein_distance(qt, ct) <= max_distance:
                    matched.add(qt)
                    break

    return matched
