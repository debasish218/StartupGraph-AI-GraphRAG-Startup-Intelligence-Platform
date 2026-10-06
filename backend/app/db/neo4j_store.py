"""Async Neo4j access layer.

All nodes carry the base label ``Entity`` with a unique ``id`` so that one node can
hold several roles (e.g. Microsoft is both a ``Company`` and an ``Investor``).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from neo4j import AsyncDriver, AsyncGraphDatabase, unit_of_work
from neo4j.graph import Node, Path, Relationship
from neo4j.time import Date, DateTime

log = logging.getLogger(__name__)

SCHEMA_STATEMENTS = [
    "CREATE CONSTRAINT entity_id IF NOT EXISTS FOR (n:Entity) REQUIRE n.id IS UNIQUE",
    "CREATE INDEX company_sector IF NOT EXISTS FOR (c:Company) ON (c.sector)",
    "CREATE INDEX round_date IF NOT EXISTS FOR (r:FundingRound) ON (r.date)",
    "CREATE INDEX entity_name IF NOT EXISTS FOR (n:Entity) ON (n.name)",
    "CREATE FULLTEXT INDEX entity_names IF NOT EXISTS FOR (n:Entity) ON EACH [n.name, n.aliases_text]",
]

# Stored with an arbitrary direction; displayed and queried as undirected.
UNDIRECTED_TYPES = {"COMPETES_WITH", "PARTNERS_WITH"}

# Human/LLM-readable schema description used by the Cypher generation agent.
GRAPH_SCHEMA = """
Node labels (every node also has label :Entity with unique property `id`):
  (:Company {id, name, description, sector, tags[], country, founded_year, employee_count,
             employee_growth_pct, website, is_startup, total_funding})
  (:Founder:Person {id, name, linkedin_url, background, previous_companies[]})
  (:Investor {id, name, type, fund_size, quality})   // corporates are both :Company and :Investor
  (:Technology {id, name, category})
  (:FundingRound {id, round_type, amount, date})      // date is a Neo4j date
  (:NewsArticle {id, title, published_at, url, event_type})

Relationships:
  (:Company)-[:FOUNDED_BY]->(:Founder)
  (:Company)-[:INVESTED_BY {rounds, total_amount, lead}]->(:Investor)   // aggregated per company
  (:Company)-[:RAISED]->(:FundingRound)
  (:FundingRound)-[:INVESTED_BY {lead: bool}]->(:Investor)
  (:Company)-[:USES_TECH]->(:Technology)
  (:Company)-[:COMPETES_WITH]-(:Company)            // stored once, query undirected
  (:Company)-[:PARTNERS_WITH {since, description}]-(:Company)
  (:Company)-[:ACQUIRED {date, amount}]->(:Company)
  (:Founder)-[:WORKED_AT]->(:Company|:Investor)
  (:Company|:Investor)-[:MENTIONED_IN]->(:NewsArticle)
""".strip()


@dataclass
class GraphResult:
    rows: list[dict[str, Any]] = field(default_factory=list)
    nodes: dict[str, dict[str, Any]] = field(default_factory=dict)
    edges: dict[str, dict[str, Any]] = field(default_factory=dict)

    def merge(self, other: GraphResult) -> GraphResult:
        self.rows.extend(other.rows)
        self.nodes.update(other.nodes)
        self.edges.update(other.edges)
        return self


def _plain(value: Any) -> Any:
    if isinstance(value, (Date, DateTime)):
        return value.iso_format()
    if isinstance(value, list):
        return [_plain(v) for v in value]
    if isinstance(value, dict):
        return {k: _plain(v) for k, v in value.items()}
    return value


class _Collector:
    """Converts driver values into JSON-safe rows and gathers graph elements."""

    def __init__(self, result: GraphResult):
        self.result = result
        self._eid_to_id: dict[str, str] = {}

    def node(self, n: Node) -> dict[str, Any]:
        props = {k: _plain(v) for k, v in n.items()}
        nid = props.get("id") or n.element_id
        self._eid_to_id[n.element_id] = nid
        labels = sorted(lbl for lbl in n.labels if lbl != "Entity")
        data = {"id": nid, "labels": labels, "name": props.get("name") or props.get("title") or nid, **props}
        data.pop("aliases_text", None)
        self.result.nodes.setdefault(nid, data)
        return data

    def rel(self, r: Relationship) -> dict[str, Any]:
        for endpoint in (r.start_node, r.end_node):
            if endpoint is not None and len(endpoint) > 0:
                self.node(endpoint)
        data = {"id": r.element_id, "type": r.type, "source": r.start_node.element_id,
                "target": r.end_node.element_id, **{k: _plain(v) for k, v in r.items()}}
        self.result.edges.setdefault(r.element_id, data)
        return data

    def finalize(self) -> None:
        """Map edge endpoints to domain ids; drop edges whose endpoints were not returned."""
        edges = {}
        for eid, e in self.result.edges.items():
            src, dst = self._eid_to_id.get(e["source"]), self._eid_to_id.get(e["target"])
            if src and dst:
                edges[eid] = {**e, "source": src, "target": dst}
        self.result.edges = edges

    def value(self, v: Any) -> Any:
        if isinstance(v, Node):
            return self.node(v)
        if isinstance(v, Relationship):
            return self.rel(v)
        if isinstance(v, Path):
            nodes = [self.node(n) for n in v.nodes]
            rels = [self.rel(r) for r in v.relationships]
            text = nodes[0]["name"]
            for i, r in enumerate(v.relationships):
                forward = r.start_node.element_id == v.nodes[i].element_id
                if r.type in UNDIRECTED_TYPES:
                    arrow = f" -[{r.type}]- "
                else:
                    arrow = f" -[{r.type}]-> " if forward else f" <-[{r.type}]- "
                text += arrow + nodes[i + 1]["name"]
            return {"path": [n["name"] for n in nodes], "nodes": [n["id"] for n in nodes],
                    "relationships": [r["type"] for r in rels], "text": text}
        if isinstance(v, list):
            return [self.value(x) for x in v]
        if isinstance(v, dict):
            return {k: self.value(x) for k, x in v.items()}
        return _plain(v)


class GraphStore:
    def __init__(self, uri: str, user: str, password: str, database: str = "neo4j"):
        self._uri, self._auth, self._database = uri, (user, password), database
        self._driver: AsyncDriver | None = None

    async def connect(self) -> None:
        self._driver = AsyncGraphDatabase.driver(self._uri, auth=self._auth, notifications_min_severity="OFF")
        await self._driver.verify_connectivity()

    async def close(self) -> None:
        if self._driver:
            await self._driver.close()

    @property
    def driver(self) -> AsyncDriver:
        if self._driver is None:
            raise RuntimeError("GraphStore is not connected")
        return self._driver

    async def ensure_schema(self) -> None:
        for stmt in SCHEMA_STATEMENTS:
            await self.write(stmt)

    async def read(self, cypher: str, params: dict[str, Any] | None = None,
                   timeout: float | None = None) -> GraphResult:  # noqa: ASYNC109 - server-side tx timeout
        """Run a query in a READ transaction (the server rejects any write)."""
        result = GraphResult()
        collector = _Collector(result)

        @unit_of_work(timeout=timeout)
        async def work(tx):
            res = await tx.run(cypher, params or {})
            return [record async for record in res]

        async with self.driver.session(database=self._database) as session:
            records = await session.execute_read(work)
        for record in records:
            result.rows.append({k: collector.value(record[k]) for k in record.keys()})  # noqa: SIM118
        collector.finalize()
        return result

    async def write(self, cypher: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        async def work(tx):
            res = await tx.run(cypher, params or {})
            return [record.data() async for record in res]

        async with self.driver.session(database=self._database) as session:
            return await session.execute_write(work)

    async def entity_catalog(self) -> list[dict[str, Any]]:
        res = await self.read(
            "MATCH (n:Entity) WHERE n:Company OR n:Investor OR n:Founder OR n:Technology "
            "RETURN n.id AS id, n.name AS name, coalesce(n.aliases, []) AS aliases, "
            "[l IN labels(n) WHERE l <> 'Entity'] AS labels"
        )
        return res.rows

    async def counts(self) -> dict[str, int]:
        res = await self.read(
            "MATCH (n:Entity) UNWIND labels(n) AS l WITH l WHERE l <> 'Entity' "
            "RETURN l AS label, count(*) AS count"
        )
        rel = await self.read("MATCH ()-[r]->() RETURN count(r) AS c")
        out = {r["label"]: r["count"] for r in res.rows}
        out["relationships"] = rel.rows[0]["c"] if rel.rows else 0
        return out
