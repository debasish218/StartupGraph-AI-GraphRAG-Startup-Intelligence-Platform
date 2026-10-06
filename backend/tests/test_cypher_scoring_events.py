import pytest

from app.agents.answer import compose_answer, compute_confidence, extract_paths, scalar_rows
from app.agents.cypher import UnsafeCypherError, build_queries, validate_cypher
from app.agents.entities import ExtractedEntities
from app.db.vector_store import chunk_text
from app.ingestion.events import extract_events_regex, parse_amount
from app.services.scoring import (
    compute_score,
    funding_score,
    hiring_score,
    investor_quality_score,
    news_score,
)
from app.services.sentiment import score_sentiment

# ---------------------------------------------------------------- Cypher safety


@pytest.mark.parametrize("cypher", [
    "MATCH (n) DETACH DELETE n",
    "MATCH (c:Company) SET c.name = 'x' RETURN c",
    "CREATE (n:Company {name: 'x'}) RETURN n",
    "MATCH (n) RETURN n; MATCH (m) DELETE m",
    "CALL apoc.cypher.runWrite('MATCH (n) DELETE n', {}) YIELD value RETURN value",
    "LOAD CSV FROM 'http://evil' AS row RETURN row",
    "MATCH (c) MERGE (c)-[:X]->(c) RETURN c",
    "MATCH (c) FOREACH (x IN [1] | SET c.a = x) RETURN c",
    "DROP INDEX entity_name",
    "MATCH (c:Company) WITH c",
])
def test_validator_rejects_unsafe(cypher):
    with pytest.raises(UnsafeCypherError):
        validate_cypher(cypher)


def test_validator_accepts_reads_and_enforces_limit():
    q = validate_cypher("```cypher\nMATCH (c:Company {id: 'openai'})-[:COMPETES_WITH]-(x) RETURN x.name\n```")
    assert q.endswith("LIMIT 100") and q.startswith("MATCH")
    assert validate_cypher("MATCH (c) RETURN c LIMIT 5000", max_limit=50).endswith("LIMIT 50")
    # keywords inside string literals are not clauses
    assert validate_cypher("MATCH (c:Company) WHERE c.description CONTAINS 'create delete' RETURN c LIMIT 3")
    assert validate_cypher("CALL db.index.fulltext.queryNodes('entity_names', 'open') YIELD node RETURN node")
    assert validate_cypher("MATCH (c) CALL (c) { MATCH (c)--(x) RETURN count(x) AS n } RETURN c, n")


def test_templates_are_parameterised():
    ents = ExtractedEntities(companies=[{"id": "openai", "name": "OpenAI", "type": "Company"}],
                             topics=["Computer Vision"], round_types=["Series B"], date_from="2025-01-01")
    for intent in ("competitors", "competitor_investors", "investors_of", "funding_search", "recommendation",
                   "company_overview", "active_investors"):
        queries = build_queries(intent, ents, 25)
        assert queries, intent
        for q in queries:
            assert "openai" not in q.cypher.lower()  # values only via params
    fq = build_queries("funding_search", ents, 25)[0]
    assert fq.params["round_types"] == ["Series B"] and "computer vision" in fq.params["terms"]


def test_templates_require_entities():
    assert build_queries("competitors", ExtractedEntities(), 10) == []
    assert build_queries("relationship", ExtractedEntities(
        companies=[{"id": "openai", "name": "OpenAI", "type": "Company"}]), 10) == []


# ---------------------------------------------------------------- scoring


def test_score_components_and_weights():
    assert funding_score(None) == 0 and funding_score(1e11) == 1 and 0.5 < funding_score(1e9) < 0.7
    assert hiring_score(-50) == 0 and hiring_score(150) == 1 and hiring_score(None) == 0.5
    assert news_score(None, 0) == 0.5
    assert news_score(1.0, 1) == pytest.approx(0.75)  # shrunk toward neutral with one article
    assert news_score(1.0, 9) == pytest.approx(0.95)
    assert investor_quality_score([]) == 0
    assert investor_quality_score([0.9, 0.9, 0.9]) == pytest.approx(0.85 * 0.9 + 0.15 * 0.3)

    s = compute_score(company_id="x", name="X", total_funding=1e9, avg_sentiment=0.5, article_count=3,
                      employee_growth_pct=40, investor_qualities=[0.95, 0.9, 0.8])
    expected = 0.35 * s.funding + 0.25 * s.news + 0.20 * s.hiring + 0.20 * s.investor_quality
    assert s.score == pytest.approx(expected, abs=1e-3)


def test_sentiment():
    assert score_sentiment("Startup raises record round amid strong growth") > 0.5
    assert score_sentiment("Company announces layoffs as lawsuit and losses mount") < -0.5
    assert score_sentiment("The company held a meeting.") == 0


# ---------------------------------------------------------------- events


def test_funding_event():
    [ev] = extract_events_regex("Exclusive: Acme Robotics raises $40M Series B led by GV",
                                "The round included participation from Craft Ventures, Y Combinator and Nvidia.")
    assert (ev.type, ev.company, ev.amount, ev.round_type) == ("funding", "Acme Robotics", 40e6, "Series B")
    assert ev.lead_investors == ["GV"] and ev.investors == ["Craft Ventures", "Y Combinator", "Nvidia"]


def test_acquisition_partnership_launch_events():
    [acq] = extract_events_regex("Nvidia acquires Run:ai for $700 million")
    assert (acq.company, acq.counterparty, acq.amount) == ("Nvidia", "Run:ai", 700e6)
    [p] = extract_events_regex("Mistral AI partners with Microsoft to bring models to Azure")
    assert (p.type, p.company, p.counterparty) == ("partnership", "Mistral AI", "Microsoft")
    [launch] = extract_events_regex("Runway launches Gen-4 video model")
    assert (launch.type, launch.company) == ("product_launch", "Runway")
    assert extract_events_regex("Why AI startups are struggling to hire") == []


def test_parse_amount():
    assert parse_amount("1.3", "B") == 1.3e9
    assert parse_amount("200", "million", "€") == pytest.approx(216e6)


def test_chunking_overlaps_and_covers_text():
    text = " ".join(f"Sentence number {i} talks about startups." for i in range(200))
    chunks = chunk_text(text, max_chars=500, overlap=100)
    assert len(chunks) > 5 and all(len(c) <= 500 for c in chunks)
    assert chunks[0].startswith("Sentence number 0") and chunks[-1].endswith("startups.")


# ---------------------------------------------------------------- answers


def _state(**kw):
    base = {"intent": "competitors", "query_type": "graph", "classification_confidence": 0.9,
            "entities": {"companies": [{"id": "openai", "name": "OpenAI", "type": "Company"}]},
            "graph": {"rows": [], "nodes": {}, "edges": {}}, "documents": [], "rankings": [], "similar": [],
            "paths": [], "notes": [], "errors": []}
    base.update(kw)
    return base


def test_compose_competitors_answer_and_confidence():
    rows = [{"company": "OpenAI", "competitor": "Anthropic", "sector": "AI", "total_funding": 2.5e10,
             "investors": ["Amazon", "Google"], "c": {"id": "openai", "labels": ["Company"]}}]
    state = _state(graph={"rows": rows, "nodes": {}, "edges": {}})
    text = compose_answer(state)
    assert "Anthropic" in text and "$25B" in text and "[G]" in text
    conf = compute_confidence(state)
    assert conf["level"] in ("medium", "high") and 0 < conf["score"] <= 1


def test_empty_results_are_reported_honestly():
    state = _state()
    assert "couldn't find" in compose_answer(state)
    assert compute_confidence(state)["level"] == "low"


def test_scalar_rows_and_paths():
    path = {"path": ["OpenAI", "Mistral AI", "Nvidia"], "nodes": ["openai", "mistral-ai", "nvidia"],
            "relationships": ["COMPETES_WITH", "INVESTED_BY"],
            "text": "OpenAI -[COMPETES_WITH]- Mistral AI -[INVESTED_BY]-> Nvidia"}
    rows = [{"investor": "Nvidia", "paths": [path], "i": {"id": "nvidia", "labels": ["Investor"]}}]
    assert scalar_rows(rows) == [{"investor": "Nvidia"}]
    assert extract_paths(rows) == [path["text"]]
