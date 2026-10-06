"""Ranking, similarity, recommendation and analytics services built on both stores."""

from __future__ import annotations

from typing import Any

from app.agents.cypher import NOT_ACQUIRED, topic_filter
from app.db.neo4j_store import GraphStore
from app.db.vector_store import VectorStore
from app.services.scoring import StartupScore, compute_score

SIMILARITY_WEIGHTS = {"embedding": 0.40, "technology": 0.25, "investor": 0.20, "sector": 0.15}
MIN_SIMILARITY = 0.2


def jaccard(a: set[str], b: set[str]) -> float:
    return len(a & b) / len(a | b) if a and b else 0.0


class RankingService:
    def __init__(self, graph: GraphStore, vectors: VectorStore):
        self.graph, self.vectors = graph, vectors

    async def score_companies(self, company_ids: list[str]) -> list[StartupScore]:
        if not company_ids:
            return []
        res = await self.graph.read(
            """MATCH (c:Company) WHERE c.id IN $ids
               OPTIONAL MATCH (c)-[:INVESTED_BY]->(i:Investor)
               RETURN c.id AS id, c.name AS name, c.sector AS sector, c.total_funding AS total_funding,
                      c.employee_growth_pct AS growth, collect(i.quality) AS qualities,
                      collect(i.name) AS investors""",
            {"ids": company_ids},
        )
        sentiment = await self.vectors.news_sentiment(company_ids)
        scores = []
        for r in res.rows:
            avg, n = sentiment.get(r["id"], (None, 0))
            scores.append(compute_score(
                company_id=r["id"], name=r["name"], total_funding=r["total_funding"], avg_sentiment=avg,
                article_count=n, employee_growth_pct=r["growth"], investor_qualities=r["qualities"],
                investors=r["investors"], sector=r["sector"],
            ))
        return sorted(scores, key=lambda s: s.score, reverse=True)

    async def rank_startups(self, terms: list[str] | None = None, limit: int = 20) -> list[StartupScore]:
        res = await self.graph.read(
            f"MATCH (c:Company) WHERE c.is_startup AND {NOT_ACQUIRED} AND {topic_filter('c')} RETURN c.id AS id",
            {"terms": [t.lower() for t in terms or []]},
        )
        return (await self.score_companies([r["id"] for r in res.rows]))[:limit]


class SimilarityService:
    def __init__(self, graph: GraphStore, vectors: VectorStore):
        self.graph, self.vectors = graph, vectors

    async def similar(self, company_id: str, limit: int = 10, different_investors: bool = False
                      ) -> list[dict[str, Any]]:
        res = await self.graph.read(
            """MATCH (c:Company) WHERE c.is_startup OR c.id = $id
               RETURN c.id AS id, c.name AS name, c.sector AS sector, coalesce(c.tags, []) AS tags,
                      c.total_funding AS total_funding,
                      [(c)-[:USES_TECH]->(t) | t.name] AS techs,
                      [(c)-[:INVESTED_BY]->(i) | i.id] AS investor_ids,
                      [(c)-[:INVESTED_BY]->(i) | i.name] AS investors""",
            {"id": company_id},
        )
        rows = {r["id"]: r for r in res.rows}
        target = rows.pop(company_id, None)
        if target is None:
            return []
        emb = await self.vectors.company_similarity(company_id, list(rows))
        weights = dict(SIMILARITY_WEIGHTS)
        if different_investors:
            weights.pop("investor")
        total_w = sum(weights.values())

        t_tech, t_inv, t_tags = set(target["techs"]), set(target["investor_ids"]), set(target["tags"])
        out = []
        for cid, r in rows.items():
            shared_inv = t_inv & set(r["investor_ids"])
            if different_investors and shared_inv:
                continue
            components = {
                "embedding": max(0.0, emb.get(cid, 0.0)),
                "technology": jaccard(t_tech, set(r["techs"])),
                "investor": jaccard(t_inv, set(r["investor_ids"])),
                "sector": 0.5 * (r["sector"] == target["sector"]) + 0.5 * jaccard(t_tags, set(r["tags"])),
            }
            score = sum(weights[k] * components[k] for k in weights) / total_w
            if score < MIN_SIMILARITY:
                continue
            id_to_name = dict(zip(r["investor_ids"], r["investors"]))
            out.append({
                "id": cid, "name": r["name"], "sector": r["sector"], "score": round(score, 3),
                "components": {k: round(v, 3) for k, v in components.items()},
                "shared_technologies": sorted(t_tech & set(r["techs"])),
                "shared_investors": sorted(id_to_name[i] for i in shared_inv),
                "investors": r["investors"], "total_funding": r["total_funding"],
            })
        return sorted(out, key=lambda x: x["score"], reverse=True)[:limit]


class AnalyticsService:
    def __init__(self, graph: GraphStore, vectors: VectorStore, ranking: RankingService,
                 similarity: SimilarityService):
        self.graph, self.vectors, self.ranking, self.similarity = graph, vectors, ranking, similarity

    async def funding_trends(self, terms: list[str] | None = None) -> list[dict[str, Any]]:
        res = await self.graph.read(
            f"""MATCH (c:Company)-[:RAISED]->(r:FundingRound) WHERE {topic_filter('c')}
                RETURN r.date.year AS year, c.sector AS sector, count(r) AS rounds,
                       sum(coalesce(r.amount, 0)) AS amount
                ORDER BY year, sector""",
            {"terms": [t.lower() for t in terms or []]},
        )
        return res.rows

    async def sector_breakdown(self) -> list[dict[str, Any]]:
        res = await self.graph.read(
            """MATCH (c:Company) WHERE c.is_startup
               RETURN c.sector AS sector, count(c) AS companies, sum(coalesce(c.total_funding, 0)) AS total_funding,
                      avg(c.employee_growth_pct) AS avg_hiring_growth
               ORDER BY total_funding DESC"""
        )
        return res.rows

    async def investor_discovery(self, terms: list[str] | None = None, limit: int = 20) -> list[dict[str, Any]]:
        res = await self.graph.read(
            f"""MATCH (c:Company)-[r:INVESTED_BY]->(i:Investor)
                WHERE c.is_startup AND {topic_filter('c')}
                WITH i, count(DISTINCT c) AS startups_backed, sum(r.rounds) AS rounds,
                     sum(CASE WHEN r.lead THEN 1 ELSE 0 END) AS rounds_led,
                     sum(coalesce(r.total_amount, 0)) AS round_volume, collect(DISTINCT c.name) AS portfolio,
                     collect(DISTINCT c.sector) AS sectors
                RETURN i.id AS id, i.name AS investor, i.type AS type, i.quality AS quality, startups_backed,
                       rounds, rounds_led, round_volume, portfolio, sectors
                ORDER BY startups_backed DESC, rounds_led DESC LIMIT $limit""",
            {"terms": [t.lower() for t in terms or []], "limit": limit},
        )
        return res.rows

    async def compare(self, company_ids: list[str]) -> dict[str, Any]:
        from app.agents.cypher import COMPANY_SUMMARY

        res = await self.graph.read(COMPANY_SUMMARY, {"ids": company_ids})
        scores = {s.company_id: s.to_dict() for s in await self.ranking.score_companies(company_ids)}
        profiles = []
        for row in res.rows:
            row["score"] = scores.get(row["id"])
            profiles.append(row)
        common = {}
        if len(profiles) >= 2:
            for key in ("investors", "technologies", "competitors", "partners"):
                sets = [set(p[key]) for p in profiles]
                common[key] = sorted(set.intersection(*sets))
        return {"companies": profiles, "in_common": common}
