"""
Context Filter & Follow-up Detection Module for Nova AI.

Ensures that:
1. Unrelated new queries are completely isolated from previous conversation context.
2. Previous assistant answers are NEVER treated as external factual knowledge.
3. Conversation context is ONLY provided when the current prompt is a genuine follow-up
   (e.g., "explain that further", "what about the second point?", "give an example of it",
    or domain continuations like "Explain pooling layers in more detail" after "Explain CNN").
"""
import re
from typing import Optional

# Common follow-up phrases that explicitly refer back to previous discussion
FOLLOW_UP_PHRASES_RE = re.compile(
    r"\b("
    r"explain\s+(that|this|it|further|more)|"
    r"tell\s+me\s+more|"
    r"more\s+detail(s)?|"
    r"in\s+more\s+detail|"
    r"elaborate(\s+on\s+(that|this|it))?|"
    r"give\s+an?\s+example(\s+of\s+(it|this|that))?|"
    r"show\s+an?\s+example|"
    r"what\s+about\s+(the\s+)?(second|first|third|last|other|former|latter|next)\b|"
    r"what\s+about\s+(it|this|that)\b|"
    r"how\s+about\s+(it|this|that)\b|"
    r"what\s+does\s+(that|this|it)\s+mean\b|"
    r"why\s+(is|are|does|did|was|were)\s+(it|that|this|they)\b|"
    r"how\s+does\s+(that|this|it)\s+work\b|"
    r"why\s+so|"
    r"continue|"
    r"go\s+on|"
    r"and\s+then|"
    r"what\s+else|"
    r"second\s+point|"
    r"first\s+point|"
    r"third\s+point"
    r")\b",
    re.I,
)

# Pronoun reference at start of a question indicating anaphoric reference
PRONOUN_REF_RE = re.compile(
    r"^\s*(and\s+|so\s+|then\s+|also\s+)?(what|how|why|where|when|which|can|could|does|is|are)\s+(it|this|that|they|these|those)\b",
    re.I,
)

# Anaphoric references inside questions (e.g., "how does X work in it?", "what are its advantages?")
ANAPHORIC_PRONOUN_RE = re.compile(
    r"\b(in|of|for|about|with|to|from|by|on|under)\s+(it|this|that|them)\b|\b(its|their)\b",
    re.I,
)

# Signals that a query is completely self-contained and introducing an independent new topic
INDEPENDENT_TOPIC_RE = re.compile(
    r"\b("
    r"who\s+is\s+the\s+(current|new|ceo|leader|president|cm|chief\s+minister)|"
    r"what\s+is\s+the\s+(latest|current|capital|population|distance|speed)|"
    r"write\s+a\s+(java|python|c\+\+|javascript|typescript|go|rust|sql|html|css)\s+(program|code|script|function|class)|"
    r"implement\s+(binary\s+search|merge\s+sort|quick\s+sort|two\s+sum|fibonacci|dijkstra)|"
    r"explain\s+in\s+detail\s+about\s+the\s+|"
    r"explain\s+in\s+detail\s+about\s+|"
    r"explain\s+detail\s+about\s+"
    r")\b",
    re.I,
)

STOPWORDS = {
    "the", "a", "an", "is", "are", "was", "were", "of", "to", "in", "on", "for",
    "and", "or", "with", "what", "how", "do", "does", "i", "can", "you", "tell", "me",
    "about", "give", "please", "my", "we", "at", "by", "from", "be", "this", "that",
    "explain", "detail", "details", "more", "question",
}


def _extract_keywords(text: str) -> set[str]:
    from ..utils.query_regularizer import regularize_query
    tokens = re.findall(r"[a-zA-Z0-9]+", (text or "").lower())
    base_keywords = {t for t in tokens if t not in STOPWORDS and len(t) > 2}
    # Add regularized tokens for spell-tolerance
    reg = regularize_query(text or "")
    for t in reg.get("normalized_tokens", []):
        if t not in STOPWORDS and len(t) > 2:
            base_keywords.add(t)
    return base_keywords


def detect_follow_up(
    query: str,
    history: Optional[list[dict]],
) -> tuple[bool, str, dict]:
    """
    Determines whether `query` is a follow-up to the preceding conversation in `history`.

    Returns
    -------
    (is_follow_up, conversation_context_text, metadata)
    """
    if not history:
        return False, "", {"reason": "empty_history"}

    # Extract clean turns from history (ignoring system turns)
    clean_turns = []
    for m in history:
        role = m.get("role", "")
        content = (m.get("content") or "").strip()
        if not content:
            continue
        # Normalize role
        norm_role = "assistant" if role in ("ai", "assistant") else "user" if role == "user" else role
        clean_turns.append({"role": norm_role, "content": content})

    if not clean_turns:
        return False, "", {"reason": "no_valid_turns"}

    # Find the last user turn and last assistant turn
    last_user_turn = None
    last_ai_turn = None
    for turn in reversed(clean_turns):
        if turn["role"] == "user" and last_user_turn is None:
            last_user_turn = turn["content"]
        elif turn["role"] == "assistant" and last_ai_turn is None:
            last_ai_turn = turn["content"]
        if last_user_turn and last_ai_turn:
            break

    if not last_user_turn:
        return False, "", {"reason": "no_prior_user_turn"}

    from ..utils.query_regularizer import regularize_query, fuzzy_token_overlap
    q_clean = query.strip()
    reg = regularize_query(q_clean)
    q_norm = reg["normalized_query"]
    q_lower = q_clean.lower()

    # 1. Check explicit follow-up phrases (on both raw and normalized query)
    has_follow_phrase = bool(FOLLOW_UP_PHRASES_RE.search(q_clean) or FOLLOW_UP_PHRASES_RE.search(q_norm))
    has_pronoun_ref = bool(PRONOUN_REF_RE.search(q_clean) or PRONOUN_REF_RE.search(q_norm))
    has_anaphoric = bool(ANAPHORIC_PRONOUN_RE.search(q_clean) or ANAPHORIC_PRONOUN_RE.search(q_norm))

    # 2. Check if this is an explicitly independent query
    is_explicit_independent = bool(INDEPENDENT_TOPIC_RE.search(q_clean) or INDEPENDENT_TOPIC_RE.search(q_norm))

    # Keyword overlap between current query and previous user + ai turns (with fuzzy tolerance)
    current_keywords = _extract_keywords(q_clean)
    last_user_keywords = _extract_keywords(last_user_turn)
    last_ai_keywords = _extract_keywords(last_ai_turn) if last_ai_turn else set()

    user_overlap = fuzzy_token_overlap(current_keywords, last_user_keywords)
    ai_overlap = fuzzy_token_overlap(current_keywords, last_ai_keywords)

    # Short query heuristic: very short queries like "why?", "how so?", "example?" are follow-ups
    word_count = len(q_clean.split())
    is_very_short = word_count <= 4 and (has_follow_phrase or has_pronoun_ref or not current_keywords)

    is_follow_up = False
    reason = "independent_query"

    if has_follow_phrase or has_pronoun_ref:
        # If it has an explicit follow-up phrase and either references previous topic or isn't a completely new prompt
        if not is_explicit_independent or (user_overlap or ai_overlap):
            is_follow_up = True
            reason = "explicit_follow_up_phrase"
        elif is_very_short:
            is_follow_up = True
            reason = "very_short_follow_up"

    elif has_anaphoric and not is_explicit_independent:
        is_follow_up = True
        reason = "anaphoric_reference"

    elif is_very_short and (user_overlap or ai_overlap):
        is_follow_up = True
        reason = "short_contextual_continuation"

    elif not is_explicit_independent:
        # Check domain continuation: e.g. "Explain pooling layers in more detail" after "Explain CNN"
        # "pooling layers" might be mentioned in the last AI response explaining CNNs
        if "in more detail" in q_lower or "detail" in q_lower or "further" in q_lower:
            if user_overlap or ai_overlap:
                is_follow_up = True
                reason = "detail_elaboration_on_previous_topic"

    # If classified as a follow-up, build structured context block for the prompt
    context_text = ""
    if is_follow_up:
        # Format concise excerpt of the last turn (max 800 chars to avoid overwhelming the prompt)
        ai_excerpt = (last_ai_turn[:800] + "...") if last_ai_turn and len(last_ai_turn) > 800 else (last_ai_turn or "")
        context_text = (
            f"Previous Question: {last_user_turn}\n"
            f"Previous Answer Summary: {ai_excerpt}\n\n"
            f"Note: The user's current question is a follow-up to the topic above. "
            f"Use this context solely to resolve references, but focus your response ENTIRELY on answering the current question."
        )

    metadata = {
        "is_follow_up": is_follow_up,
        "reason": reason,
        "last_user_turn": last_user_turn[:60] if last_user_turn else "",
        "user_overlap": list(user_overlap),
        "ai_overlap": list(ai_overlap),
    }

    return is_follow_up, context_text, metadata
