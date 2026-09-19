import pytest
from app.utils.query_regularizer import regularize_query, fuzzy_token_overlap, levenshtein_distance
from app.orchestrator.intent_router import classify_intent, is_coding_question
from app.retrieval.keyword_search import bm25_score_chunks


def test_regularize_query_programming_languages():
    res = regularize_query("writ a binnary serch algorthm in pythn and jva")
    norm = res["normalized_query"]
    assert "write" in norm
    assert "binary" in norm
    assert "search" in norm
    assert "algorithm" in norm
    assert "python" in norm
    assert "java" in norm


def test_regularize_query_intent_keywords():
    res = regularize_query("whast is the currnt cm of karnatka")
    norm = res["normalized_query"]
    assert "what" in norm
    assert "current" in norm
    assert "karnataka" in norm


def test_levenshtein_distance():
    assert levenshtein_distance("python", "python") == 0
    assert levenshtein_distance("pythn", "python") == 1
    assert levenshtein_distance("algorthm", "algorithm") == 1
    assert levenshtein_distance("cat", "dog") == 3


def test_fuzzy_token_overlap():
    query_terms = {"pythn", "algorthm", "binnary"}
    corpus_terms = {"python", "algorithm", "binary", "sorting"}
    overlap = fuzzy_token_overlap(query_terms, corpus_terms, max_distance=1)
    assert "pythn" in overlap
    assert "algorthm" in overlap
    assert "binnary" in overlap


def test_intent_router_with_spelling_mistakes():
    # Coding intent with typos
    assert classify_intent("writ a pythn progrm for binary serch") == "coding"
    assert is_coding_question("writ a pythn progrm for binary serch") is True

    # Current info with typos
    assert classify_intent("whast is the currnt cm of karnatka") == "current_info"

    # Greeting with typos
    assert classify_intent("hii there") == "greeting"


def test_bm25_with_spelling_tolerance():
    chunks = [
        {"id": "1", "content": "This document covers the binary search algorithm in Python and data structures."},
        {"id": "2", "content": "Cooking recipes and culinary history of Karnataka."},
    ]
    # Query with spelling mistake 'pythn' and 'algorthm'
    scored = bm25_score_chunks(["pythn", "algorthm"], chunks)
    assert len(scored) > 0
    assert scored[0]["id"] == "1"
    assert scored[0]["keywordScore"] > 0
