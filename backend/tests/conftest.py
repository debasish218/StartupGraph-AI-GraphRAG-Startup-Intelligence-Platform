import json
from pathlib import Path

import pytest

from app.agents.entities import EntityCatalog
from app.services.graph_writer import tech_id

SEED = Path(__file__).resolve().parents[1] / "data" / "seed"


def _load(name: str):
    return json.loads((SEED / name).read_text())


@pytest.fixture(scope="session")
def catalog() -> EntityCatalog:
    """Gazetteer built straight from the seed files (mirrors what Neo4j returns)."""
    companies = _load("companies.json")
    investors = {i["id"]: i for i in _load("investors.json")}
    rows = []
    for c in companies:
        labels = ["Company"] + (["Investor"] if c["id"] in investors else [])
        rows.append({"id": c["id"], "name": c["name"], "aliases": c.get("aliases") or [], "labels": labels})
    company_ids = {c["id"] for c in companies}
    for i in investors.values():
        if i["id"] not in company_ids:
            rows.append({"id": i["id"], "name": i["name"], "aliases": i.get("aliases") or [], "labels": ["Investor"]})
    for f in _load("founders.json"):
        rows.append({"id": f["id"], "name": f["name"], "aliases": [], "labels": ["Founder", "Person"]})
    for t in _load("relationships.json")["technologies"]:
        rows.append({"id": tech_id(t["name"]), "name": t["name"], "aliases": [], "labels": ["Technology"]})
    return EntityCatalog(rows)
