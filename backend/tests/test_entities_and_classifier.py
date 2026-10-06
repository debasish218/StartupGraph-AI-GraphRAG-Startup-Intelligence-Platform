import pytest

from app.agents.classifier import classify_rules
from app.agents.entities import extract_entities_rules, merge_llm_entities


def ids(group):
    return [e["id"] for e in group]


def test_extracts_company_and_employer(catalog):
    e = extract_entities_rules("Show AI startups founded by ex-Google employees.", catalog)
    assert ids(e.employers) == ["google"]
    assert e.companies == []
    assert e.topics == ["Artificial Intelligence"]


def test_specific_topic_replaces_generic_ai(catalog):
    e = extract_entities_rules("Which AI startups in computer vision raised money?", catalog)
    assert e.topics == ["Computer Vision"]


def test_round_and_strict_date_filters(catalog):
    e = extract_entities_rules("Which companies raised Series B after 2024 and operate in Computer Vision?", catalog)
    assert e.round_types == ["Series B"]
    assert e.date_from == "2025-01-01" and e.date_strict
    assert "Computer Vision" in e.topics


def test_since_is_inclusive(catalog):
    e = extract_entities_rules("Seed rounds since 2023", catalog)
    assert e.round_types == ["Seed"] and e.date_from == "2023-01-01" and not e.date_strict


def test_multiple_entities_and_corporate_roles(catalog):
    e = extract_entities_rules("Show the relationship between OpenAI, Anthropic, Microsoft, and Google.", catalog)
    assert ids(e.companies) == ["openai", "anthropic", "microsoft", "google"]


def test_ambiguous_words_need_capitalisation(catalog):
    e = extract_entities_rules("Which startups can scale quickly and thrive?", catalog)
    assert e.companies == [] and e.investors == []
    e2 = extract_entities_rules("Who invests in Scale AI?", catalog)
    assert ids(e2.companies) == ["scale-ai"]


def test_aliases_resolve(catalog):
    e = extract_entities_rules("What has a16z backed?", catalog)
    assert ids(e.investors) == ["a16z"]


def test_entity_name_does_not_leak_into_topics(catalog):
    e = extract_entities_rules("Who invested in Figure AI?", catalog)
    assert ids(e.companies) == ["figure-ai"]
    assert e.topics == []


def test_llm_entities_are_resolved_through_catalog(catalog):
    base = extract_entities_rules("startups like that lab", catalog)
    merged = merge_llm_entities(base, {"companies": ["Anthropic PBC", "Totally Fake Corp"]}, catalog)
    assert ids(merged.companies) == []  # fuzzy match too weak for "Anthropic PBC"; fake rejected
    merged = merge_llm_entities(base, {"companies": ["anthropic"]}, catalog)
    assert ids(merged.companies) == ["anthropic"]


@pytest.mark.parametrize("question,intent,query_type", [
    ("What is OpenAI?", "general", "vector"),
    ("Who funds OpenAI competitors?", "competitor_investors", "graph"),
    ("Compare OpenAI and Anthropic", "compare", "hybrid"),
    ("Which startups compete with OpenAI?", "competitors", "graph"),
    ("Which investors actively fund AI startups?", "active_investors", "graph"),
    ("Show AI startups founded by ex-Google employees.", "founder_background", "graph"),
    ("Which startups are similar to Anthropic but funded by different investors?", "similar_companies", "hybrid"),
    ("Which companies raised Series B after 2024 and operate in Computer Vision?", "funding_search", "graph"),
    ("Show the relationship between OpenAI, Anthropic, Microsoft, and Google.", "relationship", "graph"),
    ("Find promising Computer Vision startups.", "recommendation", "hybrid"),
    ("Who invested in Mistral AI?", "investors_of", "graph"),
    ("Who founded Anthropic?", "founders_of", "graph"),
    ("Which companies has Nvidia acquired?", "acquisitions", "graph"),
    ("What has Sequoia Capital invested in?", "investor_portfolio", "graph"),
    ("Latest news about Perplexity", "general", "vector"),
    ("Which startups compete in robotics?", "recommendation", "hybrid"),
    ("Who are the competitors of Zorblax Industries?", "competitors", "graph"),
])
def test_classification(catalog, question, intent, query_type):
    cls = classify_rules(question, extract_entities_rules(question, catalog))
    assert (cls.intent, cls.query_type) == (intent, query_type)


def test_different_investors_flag(catalog):
    q = "Which startups are similar to Anthropic but funded by different investors?"
    assert classify_rules(q, extract_entities_rules(q, catalog)).different_investors
    q2 = "Find companies similar to Anthropic"
    assert not classify_rules(q2, extract_entities_rules(q2, catalog)).different_investors
