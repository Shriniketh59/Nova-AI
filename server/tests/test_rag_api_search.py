import os
import sys
import time
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "rag_api"))

import main as rag_main  # noqa: E402


def test_is_research_query_flags_research_phrasing():
    assert rag_main.is_research_query("explain transformers in depth")
    assert rag_main.is_research_query("compare Python and Go")
    assert rag_main.is_research_query("give a comprehensive analysis of inflation")
    assert not rag_main.is_research_query("what time is it in tokyo")
    assert not rag_main.is_research_query("capital of france")


def test_expand_search_queries_normal_vs_research():
    normal = rag_main.expand_search_queries("capital of france")
    assert normal == ["capital of france"]

    research = rag_main.expand_search_queries("explain transformer architecture")
    assert research[0] == "explain transformer architecture"
    assert len(research) > 1
    assert len(research) <= 4
    # no duplicate variants
    assert len(research) == len(set(v.lower() for v in research))


def test_group_sources_buckets_by_domain_signal():
    sources = [
        {"title": "CDC guidance", "url": "https://www.cdc.gov/page"},
        {"title": "Attention paper", "url": "https://arxiv.org/abs/1706.03762"},
        {"title": "Docs", "url": "https://docs.python.org/3/"},
        {"title": "BBC story", "url": "https://bbc.com/news/1"},
        {"title": "Random blog", "url": "https://randomblog.xyz/post"},
    ]
    groups = rag_main.group_sources(sources)
    assert any("cdc" in s["url"] for s in groups["official"])
    assert any("arxiv" in s["url"] for s in groups["research"])
    assert any("docs.python" in s["url"] for s in groups["documentation"])
    assert any("bbc" in s["url"] for s in groups["news"])
    assert any("randomblog" in s["url"] for s in groups["other"])


def test_dedupe_sources_drops_same_url_and_same_domain_title():
    sources = [
        {"title": "Foo Bar", "url": "https://example.com/a"},
        {"title": "Foo Bar", "url": "https://example.com/a"},  # exact dup
        {"title": "Foo Bar!!", "url": "https://example.com/a-copy"},  # same domain+title
        {"title": "Different", "url": "https://example.com/b"},
    ]
    ranked = rag_main.rank_sources(sources)
    urls = [s["url"] for s in ranked]
    assert urls.count("https://example.com/a") == 1
    assert "https://example.com/a-copy" not in urls
    assert "https://example.com/b" in urls


def test_search_cache_hit_avoids_second_ddgs_call():
    rag_main._search_cache.clear()
    call_count = {"n": 0}

    class FakeDDGS:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def text(self, query, max_results):
            call_count["n"] += 1
            return [{"title": "T", "href": "https://example.com/x", "body": "snippet"}]

    with patch.object(rag_main, "DDGS", FakeDDGS):
        first = rag_main._ddgs_search("some query", 5)
        second = rag_main._ddgs_search("some query", 5)

    assert call_count["n"] == 1
    assert first == second


def test_search_cache_expires_after_ttl():
    rag_main._search_cache.clear()
    rag_main._cache_set("k", [{"title": "old"}])
    entry = rag_main._search_cache["k"]
    # Force it to already be expired.
    rag_main._search_cache["k"] = (time.time() - 1, entry[1])
    assert rag_main._cache_get("k") is None
    assert "k" not in rag_main._search_cache


def test_web_search_runs_variants_in_parallel_and_merges_dedupes():
    rag_main._search_cache.clear()
    seen_queries = []

    class FakeDDGS:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def text(self, query, max_results):
            seen_queries.append(query)
            time.sleep(0.05)
            return [
                {"title": f"Result for {query}", "url_key": query, "href": f"https://arxiv.org/{hash(query) % 1000}", "body": "s"},
            ]

    with patch.object(rag_main, "DDGS", FakeDDGS):
        start = time.time()
        results = rag_main.web_search("explain transformer architecture in depth")
        elapsed = time.time() - start

    # research query -> multiple variants searched
    assert len(seen_queries) > 1
    # ran concurrently: wall time should be well under len(variants)*0.05s serial time
    assert elapsed < 0.05 * len(seen_queries)
    assert isinstance(results, list)
