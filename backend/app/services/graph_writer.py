"""Idempotent (MERGE-based) writes to the knowledge graph.

Shared by the seed loader and the news intelligence pipeline.
"""

from __future__ import annotations

from typing import Any

from app.db.neo4j_store import GraphStore
from app.utils import slugify


def tech_id(name: str) -> str:
    return f"tech-{slugify(name)}"


def round_id(company_id: str, round_type: str, date: str) -> str:
    return f"round-{company_id}-{slugify(round_type)}-{date}"


class GraphWriter:
    def __init__(self, graph: GraphStore):
        self.graph = graph

    async def upsert_technologies(self, techs: list[dict[str, Any]]) -> None:
        rows = [{"id": tech_id(t["name"]), "name": t["name"], "category": t.get("category")} for t in techs]
        await self.graph.write(
            """UNWIND $rows AS row
               MERGE (t:Entity {id: row.id}) SET t:Technology, t.name = row.name,
                 t.category = coalesce(row.category, t.category), t.aliases_text = row.name""",
            {"rows": rows},
        )

    async def upsert_companies(self, companies: list[dict[str, Any]]) -> None:
        rows = []
        for c in companies:
            aliases = c.get("aliases")  # None -> keep existing aliases
            rows.append({
                "id": c["id"], "aliases": aliases,
                "techs": [{"id": tech_id(t), "name": t} for t in c.get("technologies") or []],
                "props": {k: c.get(k) for k in (
                    "name", "description", "sector", "tags", "country", "founded_year", "employee_count",
                    "employee_growth_pct", "website", "github_org", "is_startup", "source",
                ) if c.get(k) is not None},
            })
        await self.graph.write(
            """UNWIND $rows AS row
               MERGE (c:Entity {id: row.id})
               SET c:Company, c += row.props, c.aliases = coalesce(row.aliases, c.aliases, [])
               SET c.aliases_text = reduce(s = '', a IN c.aliases | s + ' ' + a)
               WITH c, row
               UNWIND row.techs AS tech
               MERGE (t:Entity {id: tech.id})
                 ON CREATE SET t:Technology, t.name = tech.name, t.aliases_text = tech.name
               MERGE (c)-[:USES_TECH]->(t)""",
            {"rows": rows},
        )

    async def ensure_company(self, name: str, **props: Any) -> str:
        """Return the id of a company by name/alias, creating a minimal node if unknown."""
        res = await self.graph.read(
            """MATCH (c:Company) WHERE toLower(c.name) = toLower($name)
                  OR any(a IN coalesce(c.aliases, []) WHERE toLower(a) = toLower($name))
               RETURN c.id AS id LIMIT 1""",
            {"name": name},
        )
        if res.rows:
            return res.rows[0]["id"]
        cid = slugify(name)
        await self.graph.write(
            """MERGE (c:Entity {id: $id})
               ON CREATE SET c:Company, c.name = $name, c.is_startup = true, c.aliases = [], c.aliases_text = '',
                             c.source = 'news', c += $props""",
            {"id": cid, "name": name, "props": {k: v for k, v in props.items() if v is not None}},
        )
        return cid

    async def ensure_investor(self, name: str) -> str:
        res = await self.graph.read(
            """MATCH (i:Entity) WHERE (i:Investor OR i:Company) AND (toLower(i.name) = toLower($name)
                  OR any(a IN coalesce(i.aliases, []) WHERE toLower(a) = toLower($name)))
               RETURN i.id AS id LIMIT 1""",
            {"name": name},
        )
        if res.rows:
            iid = res.rows[0]["id"]
            await self.graph.write("MATCH (i:Entity {id: $id}) SET i:Investor", {"id": iid})
            return iid
        iid = slugify(name)
        await self.graph.write(
            """MERGE (i:Entity {id: $id})
               ON CREATE SET i:Investor, i.name = $name, i.type = 'Unknown', i.quality = 0.6,
                             i.aliases = [], i.aliases_text = ''""",
            {"id": iid, "name": name},
        )
        return iid

    async def upsert_investors(self, investors: list[dict[str, Any]]) -> None:
        rows = [{
            "id": i["id"], "name": i["name"], "type": i.get("type"), "fund_size": i.get("fund_size"),
            "quality": i.get("quality", 0.6), "aliases": i.get("aliases") or [],
        } for i in investors]
        await self.graph.write(
            """UNWIND $rows AS row
               MERGE (i:Entity {id: row.id})
               SET i:Investor, i.name = coalesce(i.name, row.name), i.type = row.type,
                   i.fund_size = row.fund_size, i.quality = row.quality,
                   i.aliases = [a IN coalesce(i.aliases, []) WHERE NOT a IN row.aliases] + row.aliases
               SET i.aliases_text = reduce(s = '', a IN i.aliases | s + ' ' + a)""",
            {"rows": rows},
        )

    async def upsert_founders(self, founders: list[dict[str, Any]]) -> None:
        rows = [{
            "id": f["id"], "founded": f.get("founded") or [], "worked_at": f.get("previous_companies") or [],
            "props": {"name": f["name"], "linkedin_url": f.get("linkedin_url"), "background": f.get("background"),
                      "aliases_text": f["name"]},
        } for f in founders]
        await self.graph.write(
            """UNWIND $rows AS row
               MERGE (f:Entity {id: row.id})
               SET f:Founder:Person, f += row.props
               WITH f, row
               CALL (f, row) {
                 UNWIND row.founded AS cid
                 MATCH (c:Entity {id: cid})
                 MERGE (c)-[:FOUNDED_BY]->(f)
               }
               CALL (f, row) {
                 UNWIND row.worked_at AS eid
                 MATCH (e:Entity {id: eid})
                 MERGE (f)-[:WORKED_AT]->(e)
               }
               WITH f
               OPTIONAL MATCH (f)-[:WORKED_AT]->(e)
               WITH f, collect(e.name) AS prev
               SET f.previous_companies = prev""",
            {"rows": rows},
        )

    async def add_funding_rounds(self, rounds: list[dict[str, Any]]) -> list[str]:
        rows = []
        for r in rounds:
            rid = round_id(r["company"], r["round_type"], r["date"])
            lead = set(r.get("lead_investors") or [])
            investors = [{"id": i, "lead": i in lead} for i in dict.fromkeys([*lead, *(r.get("investors") or [])])]
            rows.append({"id": rid, "company": r["company"], "round_type": r["round_type"],
                         "amount": r.get("amount"), "date": r["date"], "investors": investors,
                         "source": r.get("source", "seed")})
        await self.graph.write(
            """UNWIND $rows AS row
               MATCH (c:Entity {id: row.company})
               MERGE (r:Entity {id: row.id})
               SET r:FundingRound, r.round_type = row.round_type, r.amount = row.amount,
                   r.date = date(row.date), r.source = row.source,
                   r.name = c.name + ' ' + row.round_type + ' (' + row.date + ')'
               MERGE (c)-[:RAISED]->(r)
               WITH r, row
               UNWIND row.investors AS inv
               MATCH (i:Entity {id: inv.id})
               SET i:Investor
               MERGE (r)-[x:INVESTED_BY]->(i)
               SET x.lead = inv.lead""",
            {"rows": rows},
        )
        return [r["id"] for r in rows]

    async def refresh_investment_aggregates(self) -> None:
        """Roll round-level investments up to Company-[:INVESTED_BY]->Investor and total_funding."""
        await self.graph.write(
            """MATCH (c:Company)-[:RAISED]->(r:FundingRound)-[x:INVESTED_BY]->(i:Investor)
               WITH c, i, count(r) AS rounds, sum(coalesce(r.amount, 0)) AS amount,
                    max(CASE WHEN x.lead THEN 1 ELSE 0 END) AS lead, max(r.date) AS last_date
               MERGE (c)-[agg:INVESTED_BY]->(i)
               SET agg.rounds = rounds, agg.total_amount = amount, agg.lead = lead = 1,
                   agg.last_round_date = last_date"""
        )
        await self.graph.write(
            """MATCH (c:Company)
               OPTIONAL MATCH (c)-[:RAISED]->(r:FundingRound)
               WITH c, sum(coalesce(r.amount, 0)) AS total, max(r.date) AS last, count(r) AS n
               SET c.total_funding = total, c.last_funding_date = last, c.funding_rounds = n"""
        )

    async def add_competitors(self, pairs: list[list[str]]) -> None:
        rows = [{"a": min(a, b), "b": max(a, b)} for a, b in pairs]
        await self.graph.write(
            """UNWIND $rows AS row
               MATCH (a:Entity {id: row.a}), (b:Entity {id: row.b})
               WHERE NOT (a)-[:COMPETES_WITH]-(b)
               MERGE (a)-[:COMPETES_WITH]->(b)""",
            {"rows": rows},
        )

    async def add_partnerships(self, partnerships: list[dict[str, Any]]) -> None:
        rows = [{"a": min(p["a"], p["b"]), "b": max(p["a"], p["b"]), "since": p.get("since"),
                 "description": p.get("description")} for p in partnerships]
        await self.graph.write(
            """UNWIND $rows AS row
               MATCH (a:Entity {id: row.a}), (b:Entity {id: row.b})
               OPTIONAL MATCH (a)-[existing:PARTNERS_WITH]-(b)
               WITH a, b, row, existing WHERE existing IS NULL
               CREATE (a)-[:PARTNERS_WITH {since: row.since, description: row.description}]->(b)""",
            {"rows": rows},
        )

    async def add_acquisitions(self, acquisitions: list[dict[str, Any]]) -> None:
        await self.graph.write(
            """UNWIND $rows AS row
               MATCH (a:Entity {id: row.acquirer}), (b:Entity {id: row.target})
               MERGE (a)-[r:ACQUIRED]->(b)
               SET r.date = CASE WHEN row.date IS NULL THEN r.date ELSE date(row.date) END,
                   r.amount = coalesce(row.amount, r.amount)""",
            {"rows": acquisitions},
        )

    async def add_article(self, article_id: str, title: str, published_at: str | None, url: str | None,
                          event_type: str | None, entity_ids: list[str]) -> None:
        await self.graph.write(
            """MERGE (n:Entity {id: $id})
               SET n:NewsArticle, n.title = $title, n.name = $title, n.url = $url, n.event_type = $event_type,
                   n.published_at = CASE WHEN $published IS NULL THEN null ELSE date($published) END
               WITH n
               UNWIND $entities AS eid
               MATCH (e:Entity {id: eid})
               MERGE (e)-[:MENTIONED_IN]->(n)""",
            {"id": article_id, "title": title, "url": url, "event_type": event_type,
             "published": published_at, "entities": entity_ids},
        )
