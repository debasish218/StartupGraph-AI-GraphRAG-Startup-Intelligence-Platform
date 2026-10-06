"""Dependency container: owns connections, services and the compiled agent workflow."""

from __future__ import annotations

import logging
from typing import Any

from app.agents.entities import EntityCatalog
from app.config import Settings, get_settings
from app.db.neo4j_store import GraphStore
from app.db.vector_store import VectorStore
from app.llm.provider import Embedder, get_chat_model, get_embedder
from app.services.graph_writer import GraphWriter
from app.services.intelligence import AnalyticsService, RankingService, SimilarityService

log = logging.getLogger(__name__)


class Container:
    def __init__(self, settings: Settings, graph: GraphStore, vectors: VectorStore, embedder: Embedder,
                 llm: Any | None):
        self.settings = settings
        self.graph = graph
        self.vectors = vectors
        self.embedder = embedder
        self.llm = llm
        self.writer = GraphWriter(graph)
        self.catalog = EntityCatalog()
        self.ranking = RankingService(graph, vectors)
        self.similarity = SimilarityService(graph, vectors)
        self.analytics = AnalyticsService(graph, vectors, self.ranking, self.similarity)
        self.workflow = None

    @classmethod
    def from_settings(cls, settings: Settings | None = None) -> Container:
        s = settings or get_settings()
        embedder = get_embedder()
        return cls(
            settings=s,
            graph=GraphStore(s.neo4j_uri, s.neo4j_user, s.neo4j_password, s.neo4j_database),
            vectors=VectorStore(s.postgres_dsn, embedder.dim, embedder.name),
            embedder=embedder,
            llm=get_chat_model(),
        )

    async def start(self, check_embedding_model: bool = True) -> None:
        from app.agents.workflow import build_workflow

        await self.graph.connect()
        await self.graph.ensure_schema()
        await self.vectors.connect()
        if check_embedding_model:
            await self.vectors.ensure_schema()
        await self.refresh_catalog()
        self.workflow = build_workflow(self)
        log.info("Container started (llm=%s, embedder=%s, entities=%d)",
                 self.settings.llm_provider, self.embedder.name, len(self.catalog))

    async def stop(self) -> None:
        await self.graph.close()
        await self.vectors.close()

    async def refresh_catalog(self) -> None:
        self.catalog.load(await self.graph.entity_catalog())

    async def is_empty(self) -> bool:
        res = await self.graph.read("MATCH (c:Company) RETURN count(c) AS n")
        return res.rows[0]["n"] == 0
