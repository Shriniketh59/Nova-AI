from app.services.prompt_builder import build_rag_prompt
from app.utils.code_validation import quick_validate_code
from app.utils.completion_guard import is_truncated


# ---------------------------------------------------------------------------
# prompt_builder — long-form vs short-form branching
# ---------------------------------------------------------------------------

def test_short_simple_question_gets_direct_answer_prompt_without_title_wrapper():
    prompt = build_rag_prompt("Some context.", "What year was this filed?")
    assert "short/direct question" in prompt
    assert "title" not in prompt.split("short/direct question")[0]


def test_long_complex_question_gets_structured_prompt():
    question = (
        "Compare the termination clauses across these two contracts, evaluate the "
        "pros and cons of each approach, and analyze which offers better protection?"
    )
    prompt = build_rag_prompt("Some context.", question)
    assert "title line" in prompt
    assert "closing summary" in prompt


def test_prompt_always_includes_grounding_rule():
    prompt = build_rag_prompt("ctx", "short q")
    assert "ONLY using the provided context" in prompt


# ---------------------------------------------------------------------------
# code_validation — ast.parse() Python syntax check
# ---------------------------------------------------------------------------

def test_valid_python_code_passes_validation():
    answer = """```python
def add(a, b):
    return a + b
```"""
    result = quick_validate_code(answer)
    assert result["pass"] is True


def test_invalid_python_syntax_is_caught():
    answer = """```python
def add(a, b)
    return a + b
```"""
    result = quick_validate_code(answer)
    assert result["pass"] is False
    assert any("syntax error" in issue.lower() for issue in result["issues"])


def test_truncated_python_code_missing_colon_and_body_is_caught():
    answer = """```python
def process(items):
    for item in items:
        if item > 0
```"""
    result = quick_validate_code(answer)
    assert result["pass"] is False


# ---------------------------------------------------------------------------
# completion_guard — truncation detection
# ---------------------------------------------------------------------------

def test_complete_sentence_is_not_flagged_truncated():
    assert is_truncated("This is a complete answer.") is False


def test_mid_sentence_cutoff_is_flagged_truncated():
    assert is_truncated("The algorithm works by iterating through the list and") is True


def test_unclosed_code_fence_is_flagged_truncated():
    assert is_truncated("Here is code:\n```python\nprint(1)") is True


def test_done_reason_length_is_always_flagged_truncated():
    assert is_truncated("A short complete sentence.", done_reason="length") is True


def test_missing_required_sections_flagged_when_required():
    text = "## Direct Answer\nSome answer.\n## Detailed Explanation\nMore text."
    assert is_truncated(text, require_sections=True) is True


def test_short_answer_not_falsely_flagged():
    assert is_truncated("Short") is False
