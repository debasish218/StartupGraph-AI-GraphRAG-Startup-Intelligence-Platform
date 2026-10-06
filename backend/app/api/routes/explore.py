"""Entity browsing and graph exploration endpoints (Relationship Explorer)."""

import asyncio

from fastapi import APIRouter, Depends, HTTPException, Query

from app.agents.answer import extract_paths
from app.agents.cypher import COMPANY_SUMMARY, build_queries, neighborhood_query
from app.agents.entities import ExtractedEntities
from app.api.deps import get_container
from app.api.schemas import GraphPayload, graph_payload
from app.container import Container

router = APIRouter(prefix="/api", tags=["explore"])


@router.get("/entities/search")
async def search_entities(q: str = Query(min_length=1, max_length=100), limit: int = Query(10, le=50),
                          c: Container = Depends(get_container)) -> list[dict]:
    """Autocomplete over companies, investors, founders and technologies."""
    needle = q.lower()
    hits: dict[str, dict] = {}
    for e in c.catalog.entries:
        s = e.surface.lower()
        if needle in s and e.id not in hits:
            hits[e.id] = {"id": e.id, "name": e.name, "labels": e.labels,
                          "rank": (not s.startswith(needle), len(s))}
    ranked = sorted(hits.values(), key=lambda h: h.pop("rank"))
    return ranked[:limit]


@router.get("/companies")
async def list_companies(q: str | None = None, sector: str | None = None, startups_only: bool = True,
                         limit: int = Query(50, le=500), c: Container = Depends(get_container)) -> list[dict]:
    res = await c.graph.read(
        """MATCH (c:Company)
           WHERE ($startups_only = false OR c.is_startup)
             AND ($q IS NULL OR toLower(c.name) CONTAINS toLower($q))
             AND ($sector IS NULL OR toLower(c.sector) = toLower($sector))
           RETURN c.id AS id, c.name AS name, c.sector AS sector, c.country AS country,
                  c.founded_year AS founded_year, c.employee_count AS employees, c.total_funding AS total_funding,
                  c.employee_growth_pct AS employee_growth_pct
           ORDER BY coalesce(c.total_funding, 0) DESC LIMIT $limit""",
        {"q": q, "sector": sector, "startups_only": startups_only, "limit": limit},
    )
    return res.rows


@router.get("/companies/{company_id}")
async def company_detail(company_id: str, c: Container = Depends(get_container)) -> dict:
    res = await c.graph.read(COMPANY_SUMMARY, {"ids": [company_id]})
    if not res.rows:
        raise HTTPException(404, f"Unknown company '{company_id}'")
    profile = res.rows[0]
    scores = await c.ranking.score_companies([company_id])
    q_emb = await asyncio.to_thread(c.embedder.embed_query, f"{profile['name']} news funding")
    docs = await c.vectors.search(q_emb, k=6, company_ids=[company_id], doc_types=["news", "market_report"])
    return {"profile": profile, "score": scores[0].to_dict() if scores else None,
            "news": [{"title": d["title"], "published_at": d["published_at"], "url": d["source_url"],
                      "sentiment": d["sentiment"], "snippet": d["content"][:300]} for d in docs]}


@router.get("/companies/{company_id}/similar")
async def similar_companies(company_id: str, different_investors: bool = False, limit: int = Query(10, le=50),
                            c: Container = Depends(get_container)) -> list[dict]:
    return await c.similarity.similar(company_id, limit=limit, different_investors=different_investors)


@router.get("/graph/neighborhood", response_model=GraphPayload)
async def neighborhood(id: str, per_node: int = Query(30, ge=1, le=100), expand: bool = False,
                       c: Container = Depends(get_container)) -> GraphPayload:
    """Neighbourhood of an entity; with expand=true also the neighbours' neighbourhoods (2 hops)."""
    q = neighborhood_query([id], per_node=per_node)
    res = await c.graph.read(q.cypher, q.params)
    if not res.nodes:
        raise HTTPException(404, f"Unknown entity '{id}'")
    if expand:
        ids = [n for n in res.nodes if n != id][:15]
        q2 = neighborhood_query(ids, per_node=max(3, per_node // 5))
        res.merge(await c.graph.read(q2.cypher, q2.params))
    return graph_payload(res.nodes, res.edges)


@router.get("/graph/relationship")
async def relationship(ids: str = Query(description="Comma-separated entity ids"),
                       c: Container = Depends(get_container)) -> dict:
    entity_ids = [i.strip() for i in ids.split(",") if i.strip()]
    if len(entity_ids) < 2:
        raise HTTPException(400, "Provide at least two entity ids")
    ents = ExtractedEntities(companies=[{"id": i, "name": i, "type": "Entity"} for i in entity_ids])
    result = None
    for q in build_queries("relationship", ents, 50):
        r = await c.graph.read(q.cypher, q.params)
        result = r if result is None else result.merge(r)
    return {"graph": graph_payload(result.nodes, result.edges), "paths": extract_paths(result.rows, limit=50)}
