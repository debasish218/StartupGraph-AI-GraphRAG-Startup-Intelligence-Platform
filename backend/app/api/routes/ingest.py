"""Ingestion endpoints (protected by X-API-Key when ADMIN_API_KEY is set)."""

from fastapi import APIRouter, Depends, HTTPException, Request

from app.api.deps import get_container, require_admin
from app.api.schemas import ArticleIn, RSSIngestIn, YCIngestIn
from app.container import Container
from app.ingestion.pipeline import NewsPipeline, enrich_github, import_csv, import_yc_companies
from app.ingestion.seed import load_seed

router = APIRouter(prefix="/api/ingest", tags=["ingest"], dependencies=[Depends(require_admin)])

MAX_CSV_BYTES = 5 * 1024 * 1024


@router.post("/article")
async def ingest_article(article: ArticleIn, c: Container = Depends(get_container)) -> dict:
    """Run one article through event detection, graph updates and embedding."""
    return await NewsPipeline(c).process_article(article.title, article.body, article.url, article.published_at,
                                                 source="api")


@router.post("/rss")
async def ingest_rss(req: RSSIngestIn, c: Container = Depends(get_container)) -> dict:
    return await NewsPipeline(c).ingest_rss(req.feeds, req.max_items)


@router.post("/yc")
async def ingest_yc(req: YCIngestIn, c: Container = Depends(get_container)) -> dict:
    return await import_yc_companies(c, req.industry, req.tag, req.batch, req.limit)


@router.post("/github")
async def ingest_github(c: Container = Depends(get_container)) -> dict:
    return await enrich_github(c)


@router.post("/csv")
async def ingest_csv(request: Request, c: Container = Depends(get_container)) -> dict:
    """Import a CSV export (send the file as the raw request body, Content-Type: text/csv)."""
    body = await request.body()
    if len(body) > MAX_CSV_BYTES:
        raise HTTPException(413, "CSV larger than 5 MB")
    try:
        return await import_csv(c, body.decode("utf-8-sig"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/seed")
async def ingest_seed(c: Container = Depends(get_container)) -> dict:
    return await load_seed(c)
