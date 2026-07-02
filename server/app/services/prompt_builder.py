from ..retrieval.complexity import classify_complexity

LONG_FORM_TIERS = {"medium", "complex", "research"}


def _is_long_form(question: str) -> bool:
    """Reuses the retrieval complexity tiering as a proxy for how substantial
    an answer should be. Short/simple factual asks stay unstructured so we
    don't wrap a one-line answer in a title+summary shell."""
    return classify_complexity(question) in LONG_FORM_TIERS


def build_rag_prompt(context: str, question: str) -> str:
    """Builds the strict context-grounded prompt used by the document RAG
    pipeline. Structure scales with query complexity: short/simple questions
    get a direct answer, longer/more complex ones get a structured breakdown."""
    long_form = _is_long_form(question)

    grounding_rules = """Answer ONLY using the provided context.
If the answer is not present in the context, clearly state that the information was not found in the uploaded documents.
Do not invent facts, names, dates, or numbers that are not present in the context."""

    if long_form:
        structure_note = """Structure your answer like this:
- A short title line summarizing the topic (as a markdown heading).
- A brief 1-2 sentence intro.
- The full explanation, addressing every part of the question, using the context.
- Concrete examples drawn from the context where relevant.
- A short closing summary if the explanation has multiple parts.

Skip any of the above that don't apply, but don't pad the answer just to fill sections."""
    else:
        structure_note = """This is a short/direct question — answer it plainly in 1-4 sentences.
Do not add a title, headings, or a summary section for an answer this short."""

    return f"""You are Nova AI, answering strictly from the user's uploaded documents.
{grounding_rules}

{structure_note}

Context:
{context}

Question:
{question}"""
