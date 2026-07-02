from app.retrieval.complexity import classify_complexity, tier_for
from app.services.task_router import classify_task, classify_topic, is_coding_question


# ---------------------------------------------------------------------------
# task_router.classify_task — topic-type routing
# ---------------------------------------------------------------------------

def test_routes_to_vision_whenever_images_are_present_regardless_of_query():
    assert classify_task("what is this", has_images=True)["type"] == "vision"
    assert classify_task("write me a python function", has_images=True, has_files=True)["type"] == "vision"


def test_routes_coding_questions_without_files_to_coding():
    assert classify_task("write a python function to reverse a string")["type"] == "coding"
    assert classify_task("fix this java null pointer exception")["type"] == "coding"
    assert classify_task("implement binary search in C++")["type"] == "coding"


def test_routes_plain_questions_without_files_to_general():
    assert classify_task("what's the weather like today")["type"] == "general"
    assert classify_task("tell me about the history of Rome")["type"] == "general"


def test_routes_to_document_comparison_when_multiple_files_and_compare_language():
    result = classify_task("compare these two documents", has_files=True, file_count=2)
    assert result["type"] == "document_comparison"


def test_routes_to_ats_for_ats_score_requests_with_files():
    result = classify_task("calculate my ats score", has_files=True, file_count=1)
    assert result["type"] == "ats"


def test_routes_to_resume_analysis_for_resume_review_requests():
    result = classify_task("please review my resume", has_files=True, file_count=1)
    assert result["type"] == "resume_analysis"


def test_routes_to_document_analysis_for_generic_analyze_requests_with_files():
    result = classify_task("summarize this document", has_files=True, file_count=1)
    assert result["type"] == "document_analysis"


def test_is_coding_question_detects_domain_specific_terms_without_verbs():
    assert is_coding_question("explain the two sum leetcode problem")
    assert not is_coding_question("what did I have for breakfast")


# ---------------------------------------------------------------------------
# complexity.classify_complexity / tier_for — complexity-tier routing
# ---------------------------------------------------------------------------

def test_short_query_is_classified_simple():
    assert classify_complexity("what is python") == "simple"


def test_long_query_is_classified_medium_or_higher():
    query = "explain how " + "the " * 15 + "system works"
    assert classify_complexity(query) in {"medium", "complex", "research"}


def test_comparison_language_is_classified_complex():
    assert classify_complexity("compare Python vs JavaScript for backend development") == "complex"


def test_research_keywords_are_classified_research():
    assert classify_complexity("give me a comprehensive literature survey of transformer architectures") == "research"


def test_tier_for_returns_matching_tier_config():
    tier = tier_for("what is python")
    assert tier["minSources"] == 3
    assert tier["topK"] == 5

    research_tier = tier_for("give me a comprehensive research survey of quantum computing")
    assert research_tier["topK"] == 15


# ---------------------------------------------------------------------------
# task_router.classify_topic — subject-matter category classification
# ---------------------------------------------------------------------------

def test_classify_topic_detects_coding():
    assert classify_topic("write a python function to reverse a string") == "coding"


def test_classify_topic_detects_math():
    assert classify_topic("solve this equation for x: 2x + 3 = 7") == "math"


def test_classify_topic_detects_medical():
    assert classify_topic("what are the symptoms and treatment for diabetes") == "medical"


def test_classify_topic_detects_legal():
    assert classify_topic("what liability clause applies to the defendant in this contract") == "legal"


def test_classify_topic_detects_biography():
    assert classify_topic("who is Marie Curie") == "biography"


def test_classify_topic_detects_news():
    assert classify_topic("what's the latest news on the election") == "news"


def test_classify_topic_detects_research():
    assert classify_topic("give me a comprehensive literature survey of transformer architectures") == "research"


def test_classify_topic_falls_back_to_chat():
    assert classify_topic("hey, how's it going") == "chat"


def test_classify_topic_categories_overlap_with_confidence_engine_contested_set():
    from app.retrieval.confidence_engine import CONTESTED_FACT_CATEGORIES

    for topic in ("biography", "medical", "legal", "news"):
        assert topic in CONTESTED_FACT_CATEGORIES
