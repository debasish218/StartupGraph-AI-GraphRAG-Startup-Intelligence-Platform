"""Ranking dashboard, recommendations, investor discovery, comparison and trends."""

from fastapi import APIRouter, Depends, HTTPException, Query

from app.agents.entities import TOPICS
from app.api.deps import get_container, topic_terms
from app.container import Container
from app.services.scoring import WEIGHTS

router = APIRouter(prefix="/api", tags=["insights"])


@router.get("/topics")
async def topics() -> list[str]:
    return sorted(TOPICS)


@router.get("/rankings")
async def rankings(topic: str | None = None, limit: int = Query(20, le=100),
                   c: Container = Depends(get_container)) -> dict:
    scores = await c.ranking.rank_startups(topic_terms(topic), limit)
    return {"weights": WEIGHTS, "topic": topic, "rankings": [s.to_dict() for s in scores]}


@router.get("/recommendations")
async def recommendations(topic: str | None = None, limit: int = Query(10, le=50),
                          c: Container = Depends(get_container)) -> list[dict]:
    """Promising startups with funding, investors, growth score and similar companies."""
    scores = await c.ranking.rank_startups(topic_terms(topic), limit)
    out = []
    for s in scores:
        similar = await c.similarity.similar(s.company_id, limit=3)
        out.append({**s.to_dict(), "growth_score": s.score,
                    "similar_companies": [{"id": x["id"], "name": x["name"], "score": x["score"]} for x in similar]})
    return out


@router.get("/investors/discover")
async def investor_discovery(topic: str | None = None, limit: int = Query(20, le=100),
                             c: Container = Depends(get_container)) -> list[dict]:
    return await c.analytics.investor_discovery(topic_terms(topic), limit)


@router.get("/compare")
async def compare(ids: str = Query(description="Comma-separated company ids"),
                  c: Container = Depends(get_container)) -> dict:
    company_ids = [i.strip() for i in ids.split(",") if i.strip()]
    if not 2 <= len(company_ids) <= 5:
        raise HTTPException(400, "Compare between 2 and 5 companies")
    return await c.analytics.compare(company_ids)


@router.get("/analytics/trends")
async def trends(topic: str | None = None, c: Container = Depends(get_container)) -> list[dict]:
    return await c.analytics.funding_trends(topic_terms(topic))


@router.get("/analytics/sectors")
async def sectors(c: Container = Depends(get_container)) -> list[dict]:
    return await c.analytics.sector_breakdown()


@router.get("/stats")
async def stats(c: Container = Depends(get_container)) -> dict:
    return {"graph": await c.graph.counts(), "documents": await c.vectors.counts(),
            "llm_provider": c.settings.llm_provider, "embedding_model": c.embedder.name}
