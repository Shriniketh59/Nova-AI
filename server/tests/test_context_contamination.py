import pytest
from app.orchestrator.context_filter import detect_follow_up
from app.orchestrator.local_orchestrator import _build_messages, _web_search, orchestrate_full


def test_detect_follow_up_independent_queries():
    """Unrelated questions in sequence must be detected as independent (is_follow_up=False)."""
    # Turn 1 history: Chief Minister question
    hist = [
        {"role": "user", "content": "Who is the current Chief Minister of Karnataka?"},
        {"role": "ai", "content": "The current Chief Minister of Karnataka is Siddaramaiah."},
    ]

    # Q2: Deep learning models (unrelated)
    q2 = "Explain pre-trained models, fine-tuning and CNN models in deep learning."
    is_fu, ctx, meta = detect_follow_up(q2, hist)
    assert not is_fu
    assert ctx == ""

    # Append Q2 & answer to history
    hist.extend([
        {"role": "user", "content": q2},
        {"role": "ai", "content": "Pre-trained models are models trained on large datasets. Fine-tuning adapts them."},
    ])

    # Q3: Coding question (unrelated)
    q3 = "Write a Java binary search program."
    is_fu, ctx, meta = detect_follow_up(q3, hist)
    assert not is_fu
    assert ctx == ""

    # Append Q3 to history
    hist.extend([
        {"role": "user", "content": q3},
        {"role": "ai", "content": "```java\npublic class BinarySearch {...}\n```"},
    ])

    # Q4: Python version question (unrelated)
    q4 = "What is the latest version of Python?"
    is_fu, ctx, meta = detect_follow_up(q4, hist)
    assert not is_fu
    assert ctx == ""


def test_detect_follow_up_positive_cases():
    """Follow-up questions must be detected as follow-up (is_follow_up=True) with prior context."""
    hist_cnn = [
        {"role": "user", "content": "Explain CNN."},
        {
            "role": "ai",
            "content": "A Convolutional Neural Network (CNN) consists of convolutional layers, pooling layers, and dense layers for computer vision.",
        },
    ]

    follow_ups = [
        "Explain pooling layers in more detail.",
        "explain that further",
        "what about the second point?",
        "give an example of it",
        "how does convolution work in it?",
        "what are its main advantages?",
    ]

    for q in follow_ups:
        is_fu, ctx, meta = detect_follow_up(q, hist_cnn)
        assert is_fu, f"Query '{q}' should be classified as a follow-up"
        assert "Explain CNN" in ctx
        assert "Previous Question" in ctx


def test_prompt_construction_isolation():
    """Verify Requirement 14: Prompt construction isolates unrelated queries."""
    # 1. Independent query with web sources:
    messages = _build_messages(
        query="Explain pre-trained models, fine-tuning and CNN models in deep learning.",
        context_text="",
        web_sources=[
            {
                "title": "Deep Learning Models Guide",
                "website": "example.org",
                "url": "https://example.org/models",
                "snippet": "Pre-trained models save training time.",
            }
        ],
        conversation_context=None,  # No follow-up context
    )

    user_content = messages[-1]["content"]
    assert "CURRENT USER QUERY:\nExplain pre-trained models" in user_content
    assert "[CURRENT WEB SOURCES]" in user_content
    assert "[RELEVANT CONVERSATION CONTEXT]" not in user_content
    assert "Chief Minister" not in user_content
    assert "Railway Minister" not in user_content

    # 2. Follow-up query with relevant conversation context:
    messages_fu = _build_messages(
        query="Explain pooling layers in more detail.",
        conversation_context="Previous Question: Explain CNN.\nPrevious Answer Summary: CNN has pooling layers.",
    )
    user_content_fu = messages_fu[-1]["content"]
    assert "CURRENT USER QUERY:\nExplain pooling layers in more detail." in user_content_fu
    assert "[RELEVANT CONVERSATION CONTEXT]" in user_content_fu
    assert "Previous Question: Explain CNN." in user_content_fu


@pytest.mark.asyncio
async def test_multiple_web_sources_retrieval():
    """Verify Requirement 8: Web search retrieves multiple independent, deduplicated sources."""
    sources = await _web_search("latest Python release", max_results=5)
    # When web is reachable, it should return multiple sources
    if sources:
        assert len(sources) >= 2, "Should return multiple web sources"
        for s in sources:
            assert "title" in s and s["title"]
            assert "url" in s and s["url"].startswith("http")
            assert "website" in s or "domain" in s
            assert "snippet" in s and len(s["snippet"]) > 0


@pytest.mark.asyncio
async def test_end_to_end_unrelated_sequence_isolation():
    """Requirement 15: Run exact sequence Q1 -> Q2 -> Q3 -> Q4.
    Verify answers are ONLY about their current query."""
    # Q1: Chief Minister of Karnataka
    res_q1 = await orchestrate_full(
        query="Who is the current Chief Minister of Karnataka?",
        conversation_history=[],
    )
    text_q1 = res_q1["text"].lower()
    print("\n[Q1 Answer]:", res_q1["text"][:150])
    assert "siddaramaiah" in text_q1 or "karnataka" in text_q1

    # Simulate history with Q1
    history = [
        {"role": "user", "content": "Who is the current Chief Minister of Karnataka?"},
        {"role": "ai", "content": res_q1["text"]},
    ]

    # Q2: Deep Learning models
    res_q2 = await orchestrate_full(
        query="Explain pre-trained models, fine-tuning and CNN models in deep learning.",
        conversation_history=history,
    )
    text_q2 = res_q2["text"].lower()
    print("\n[Q2 Answer]:", res_q2["text"][:150])
    # MUST contain deep learning concepts
    assert "model" in text_q2 or "cnn" in text_q2 or "learning" in text_q2
    # MUST NOT contain Karnataka or Chief Minister from Q1
    assert "karnataka" not in text_q2, "Q2 leaked Q1 context (karnataka)!"
    assert "siddaramaiah" not in text_q2, "Q2 leaked Q1 context (siddaramaiah)!"
    assert "chief minister" not in text_q2, "Q2 leaked Q1 context (chief minister)!"

    # Simulate history with Q2
    history.extend([
        {"role": "user", "content": "Explain pre-trained models, fine-tuning and CNN models in deep learning."},
        {"role": "ai", "content": res_q2["text"]},
    ])

    # Q3: Java Binary Search
    res_q3 = await orchestrate_full(
        query="Write a Java binary search program.",
        conversation_history=history,
    )
    text_q3 = res_q3["text"]
    print("\n[Q3 Answer]:", text_q3[:150])
    # MUST be Java binary search
    assert "binarySearch" in text_q3 or "binary_search" in text_q3 or "class" in text_q3
    # MUST NOT contain Karnataka or deep learning models from earlier
    assert "karnataka" not in text_q3.lower()
    assert "siddaramaiah" not in text_q3.lower()

    # Simulate history with Q3
    history.extend([
        {"role": "user", "content": "Write a Java binary search program."},
        {"role": "ai", "content": text_q3},
    ])

    # Q4: Latest version of Python
    res_q4 = await orchestrate_full(
        query="What is the latest version of Python?",
        conversation_history=history,
    )
    text_q4 = res_q4["text"].lower()
    print("\n[Q4 Answer]:", res_q4["text"][:150])
    assert "python" in text_q4
    assert "3." in text_q4
    assert "karnataka" not in text_q4
    assert "binary search" not in text_q4


@pytest.mark.asyncio
async def test_end_to_end_follow_up_sequence():
    """Requirement 16: Test follow-up sequence Q1: Explain CNN -> Q2: Explain pooling layers in more detail."""
    # Q1: Explain CNN
    res_q1 = await orchestrate_full(
        query="Explain CNN.",
        conversation_history=[],
    )
    print("\n[Follow-up Q1 Answer]:", res_q1["text"][:150])

    history = [
        {"role": "user", "content": "Explain CNN."},
        {"role": "ai", "content": res_q1["text"]},
    ]

    # Q2: Follow-up on pooling layers
    res_q2 = await orchestrate_full(
        query="Explain pooling layers in more detail.",
        conversation_history=history,
    )
    text_q2 = res_q2["text"].lower()
    print("\n[Follow-up Q2 Answer]:", res_q2["text"][:150])
    assert "pool" in text_q2
    # Should explain pooling in neural network / feature map / dimension reduction context
    assert "feature" in text_q2 or "dimension" in text_q2 or "cnn" in text_q2 or "downsampl" in text_q2 or "max" in text_q2
