"""FastAPI application entrypoint."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.routes import explore, ingest, insights, query
from app.config import get_settings
from app.container import Container
from app.ingestion.pipeline import NewsPipeline
from app.ingestion.seed import load_seed

settings = get_settings()
logging.basicConfig(level=settings.log_level, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("startupgraph")


async def rss_poller(container: Container, minutes: int) -> None:
    pipeline = NewsPipeline(container)
    while True:
        try:
            await pipeline.ingest_rss()
        except Exception:  # noqa: BLE001 - keep polling
            log.exception("RSS poll failed")
        await asyncio.sleep(minutes * 60)


@asynccontextmanager
async def lifespan(app: FastAPI):
    container = Container.from_settings(settings)
    await container.start()
    if settings.seed_on_startup and await container.is_empty():
        log.info("Empty knowledge graph: loading seed dataset")
        await load_seed(container)
    app.state.container = container
    poller = None
    if settings.rss_poll_minutes:
        poller = asyncio.create_task(rss_poller(container, settings.rss_poll_minutes))
    try:
        yield
    finally:
        if poller:
            poller.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await poller
        await container.stop()


app = FastAPI(
    title=settings.app_name,
    version="1.0.0",
    description="GraphRAG startup intelligence: Neo4j knowledge graph + pgvector + LangGraph agents.",
    lifespan=lifespan,
)
app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origin_list, allow_credentials=False,
                   allow_methods=["*"], allow_headers=["*"])
for r in (query.router, explore.router, insights.router, ingest.router):
    app.include_router(r)


@app.exception_handler(Exception)
async def unhandled(request: Request, exc: Exception) -> JSONResponse:
    log.exception("Unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})


@app.get("/health", tags=["ops"])
async def health() -> dict:
    return {"status": "ok"}


@app.get("/ready", tags=["ops"])
async def ready(request: Request) -> JSONResponse:
    c: Container = request.app.state.container
    checks = {}
    try:
        await c.graph.read("RETURN 1 AS ok")
        checks["neo4j"] = "ok"
    except Exception as exc:  # noqa: BLE001
        checks["neo4j"] = f"error: {exc}"
    try:
        await c.vectors.counts()
        checks["postgres"] = "ok"
    except Exception as exc:  # noqa: BLE001
        checks["postgres"] = f"error: {exc}"
    ok = all(v == "ok" for v in checks.values())
    return JSONResponse(status_code=200 if ok else 503, content={"status": "ok" if ok else "degraded", **checks})
