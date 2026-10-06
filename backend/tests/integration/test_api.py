"""End-to-end tests against real Neo4j + PostgreSQL (seeded automatically on startup).

Run:  docker compose up -d neo4j postgres && pytest -m integration
"""

import socket
from urllib.parse import urlparse

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings

pytestmark = pytest.mark.integration


def _reachable(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=1):
            return True
    except OSError:
        return False


@pytest.fixture(scope="module")
def client():
    s = get_settings()
    neo4j, pg = urlparse(s.neo4j_uri), urlparse(s.postgres_dsn)
    if not (_reachable(neo4j.hostname, neo4j.port or 7687) and _reachable(pg.hostname, pg.port or 5432)):
        pytest.skip("Neo4j/PostgreSQL not reachable")
    from app.main import app

    with TestClient(app) as c:
        yield c


def ask(client, question: str) -> dict:
    r = client.post("/api/query", json={"question": question})
    assert r.status_code == 200, r.text
    return r.json()


def test_ready(client):
    assert client.get("/ready").json()["status"] == "ok"


def test_competitors(client):
    d = ask(client, "Which startups compete with OpenAI?")
    assert d["intent"] == "competitors" and d["query_type"] == "graph"
    assert "Anthropic" in d["answer"]
    assert any(e["type"] == "COMPETES_WITH" for e in d["graph"]["edges"])
    assert d["confidence"]["level"] == "high"
    assert [t["agent"] for t in d["trace"]] == [
        "query_classification", "entity_extraction", "graph_retrieval", "ranking", "answer_generation"]


def test_multi_hop_competitor_investors(client):
    d = ask(client, "Who funds OpenAI competitors?")
    assert d["intent"] == "competitor_investors"
    assert "Nvidia" in d["answer"]
    assert any("COMPETES_WITH" in p and "INVESTED_BY" in p for p in d["paths"])


def test_active_investors(client):
    d = ask(client, "Which investors actively fund AI startups?")
    assert d["intent"] == "active_investors" and "Nvidia" in d["answer"]
    assert d["graph"]["nodes"]


def test_founder_background(client):
    d = ask(client, "Show AI startups founded by ex-Google employees.")
    assert d["intent"] == "founder_background"
    for company in ("Anthropic", "Cohere", "Character.AI", "Mistral AI"):  # Mistral via Google DeepMind
        assert company in d["answer"]
    assert "Roboflow" not in d["answer"]


def test_similar_with_different_investors(client):
    d = ask(client, "Which startups are similar to Anthropic but funded by different investors?")
    assert d["intent"] == "similar_companies" and d["similar"]
    assert all(not s["shared_investors"] for s in d["similar"])
    assert all(s["id"] != "anthropic" for s in d["similar"])


def test_funding_filter(client):
    d = ask(client, "Which companies raised Series B since 2024 in computer vision?")
    assert d["intent"] == "funding_search"
    assert "Roboflow" in d["answer"] and "Voxel51" in d["answer"]
    assert "Mistral" not in d["answer"]  # Series B 2024 but not computer vision


def test_relationship(client):
    d = ask(client, "Show the relationship between OpenAI, Anthropic, Microsoft, and Google.")
    assert d["intent"] == "relationship"
    edge_types = {e["type"] for e in d["graph"]["edges"]}
    assert {"INVESTED_BY", "COMPETES_WITH", "PARTNERS_WITH"} <= edge_types


def test_vector_question(client):
    d = ask(client, "What is OpenAI?")
    assert d["query_type"] == "vector" and d["documents"]
    assert any("openai" in doc["company_ids"] for doc in d["documents"][:3])
    assert any(s["id"].startswith("D") for s in d["sources"])


def test_hybrid_compare(client):
    d = ask(client, "Compare OpenAI and Anthropic")
    assert d["query_type"] == "hybrid" and d["documents"] and d["graph"]["nodes"]
    assert {r["company_id"] for r in d["rankings"]} == {"openai", "anthropic"}


def test_recommendation(client):
    d = ask(client, "Find promising Computer Vision startups.")
    assert d["intent"] == "recommendation" and len(d["rankings"]) >= 5
    scores = [r["score"] for r in d["rankings"]]
    assert scores == sorted(scores, reverse=True)


def test_unknown_entity_falls_back_to_vector(client):
    d = ask(client, "Who are the competitors of Zorblax Industries?")
    assert d["query_type"] == "vector"
    assert d["notes"]


def test_explorer_and_insight_endpoints(client):
    assert client.get("/api/entities/search", params={"q": "anth"}).json()[0]["id"] == "anthropic"
    nb = client.get("/api/graph/neighborhood", params={"id": "openai"}).json()
    assert {"Company", "Investor", "Founder", "Technology"} <= {n["type"] for n in nb["nodes"]}
    assert client.get("/api/graph/neighborhood", params={"id": "nope"}).status_code == 404
    rel = client.get("/api/graph/relationship", params={"ids": "openai,microsoft"}).json()
    assert rel["paths"]
    rk = client.get("/api/rankings", params={"topic": "Computer Vision"}).json()
    assert rk["weights"]["funding"] == 0.35 and rk["rankings"]
    assert client.get("/api/compare", params={"ids": "openai"}).status_code == 400
    assert client.get("/api/companies/anthropic").json()["profile"]["name"] == "Anthropic"
    assert client.get("/api/investors/discover").json()[0]["startups_backed"] >= 1


def test_ingest_requires_key_when_configured(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "admin_api_key", "secret")
    r = client.post("/api/ingest/article", json={"title": "Some headline here", "body": ""})
    assert r.status_code == 401
