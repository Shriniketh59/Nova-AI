from app.retrieval.source_trust import classify_domain, rank_sources, count_trust_tiers


def test_classifies_official_reference_community_unknown_domains():
    assert classify_domain("https://www.cdc.gov/some-page") == "official"
    assert classify_domain("https://mit.edu/about") == "official"
    assert classify_domain("https://en.wikipedia.org/wiki/Foo") == "reference"
    assert classify_domain("https://stackoverflow.com/questions/1") == "community"
    assert classify_domain("https://random-seo-blog.xyz/article") == "unknown"
    assert classify_domain("not a url") == "unknown"


def test_tags_sources_with_trust_tier_without_dropping_any():
    sources = [
        {"url": "https://random-seo-blog.xyz/a"},
        {"url": "https://cdc.gov/b"},
        {"url": "https://stackoverflow.com/c"},
    ]
    ranked = rank_sources(sources)
    assert len(ranked) == 3
    assert next(s for s in ranked if "cdc" in s["url"])["trustTier"] == "official"


def test_counts_sources_per_trust_tier():
    sources = [{"trustTier": "official"}, {"trustTier": "unknown"}, {"trustTier": "unknown"}]
    assert count_trust_tiers(sources) == {"official": 1, "reference": 0, "community": 0, "unknown": 2}
