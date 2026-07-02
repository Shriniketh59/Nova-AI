from app.agents.research_agent import detect_fact_disagreements


def test_flags_year_disagreement_between_two_sources_about_the_same_entity():
    evidence = [
        {"title": "Source A", "snippet": "Marcus Wilkins founded Initech in 1998."},
        {"title": "Source B", "snippet": "Marcus Wilkins founded Initech in 2003."},
    ]
    disagreements = detect_fact_disagreements(evidence)
    assert len(disagreements) == 1
    assert disagreements[0]["factType"] == "year"
    assert disagreements[0]["valueA"] == "1998"
    assert disagreements[0]["valueB"] == "2003"


def test_does_not_flag_sources_about_different_entities_even_if_years_differ():
    evidence = [
        {"title": "Source A", "snippet": "Marcus Wilkins founded Initech in 1998."},
        {"title": "Source B", "snippet": "Priya Chandran founded Globex in 2003."},
    ]
    assert detect_fact_disagreements(evidence) == []


def test_does_not_flag_sources_that_agree_on_the_year():
    evidence = [
        {"title": "Source A", "snippet": "Marcus Wilkins founded Initech in 1998."},
        {"title": "Source B", "snippet": "Marcus Wilkins started Initech back in 1998."},
    ]
    assert detect_fact_disagreements(evidence) == []
