"""PostgreSQL + pgvector document store."""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from datetime import date
from typing import Any

import numpy as np
import psycopg
from pgvector.psycopg import register_vector_async
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

log = logging.getLogger(__name__)


@dataclass
class Document:
    doc_type: str  # company_profile | news | funding_report | market_report
    title: str
    content: str
    company_ids: list[str]
    source: str = "seed"
    source_url: str | None = None
    published_at: date | None = None
    sentiment: float | None = None

    @property
    def doc_key(self) -> str:
        basis = self.source_url or f"{self.doc_type}|{self.title}"
        return hashlib.sha256(basis.encode()).hexdigest()[:32]


def chunk_text(text: str, max_chars: int = 900, overlap: int = 150) -> list[str]:
    """Split on paragraph/sentence boundaries into overlapping chunks."""
    text = " ".join(text.split())
    if len(text) <= max_chars:
        return [text]
    chunks, start = [], 0
    while start < len(text):
        end = min(start + max_chars, len(text))
        if end < len(text):
            cut = text.rfind(". ", start + max_chars // 2, end)
            if cut != -1:
                end = cut + 1
        chunks.append(text[start:end].strip())
        if end >= len(text):
            break
        start = max(end - overlap, start + 1)
    return chunks


class VectorStore:
    def __init__(self, dsn: str, dim: int, model_name: str = "unknown"):
        self._dsn = dsn
        self.dim = dim
        self.model_name = model_name
        self._pool: AsyncConnectionPool | None = None

    async def connect(self) -> None:
        async with await psycopg.AsyncConnection.connect(self._dsn, autocommit=True) as conn:
            await conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
        self._pool = AsyncConnectionPool(
            self._dsn, min_size=1, max_size=10, open=False, configure=register_vector_async
        )
        await self._pool.open(wait=True)

    async def close(self) -> None:
        if self._pool:
            await self._pool.close()

    @property
    def pool(self) -> AsyncConnectionPool:
        if self._pool is None:
            raise RuntimeError("VectorStore is not connected")
        return self._pool

    async def ensure_schema(self) -> None:
        d = int(self.dim)
        async with self.pool.connection() as conn:
            await conn.execute(f"""
                CREATE TABLE IF NOT EXISTS documents (
                    id BIGSERIAL PRIMARY KEY,
                    doc_key TEXT UNIQUE NOT NULL,
                    doc_type TEXT NOT NULL,
                    title TEXT NOT NULL,
                    content TEXT NOT NULL,
                    source TEXT NOT NULL DEFAULT 'seed',
                    source_url TEXT,
                    published_at DATE,
                    company_ids TEXT[] NOT NULL DEFAULT '{{}}',
                    sentiment REAL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
                );
                CREATE TABLE IF NOT EXISTS chunks (
                    id BIGSERIAL PRIMARY KEY,
                    document_id BIGINT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
                    chunk_index INT NOT NULL,
                    content TEXT NOT NULL,
                    embedding vector({d}) NOT NULL
                );
                CREATE TABLE IF NOT EXISTS company_embeddings (
                    company_id TEXT PRIMARY KEY,
                    embedding vector({d}) NOT NULL,
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
                );
                CREATE INDEX IF NOT EXISTS chunks_embedding_hnsw
                    ON chunks USING hnsw (embedding vector_cosine_ops);
                CREATE INDEX IF NOT EXISTS documents_company_ids ON documents USING gin (company_ids);
                CREATE INDEX IF NOT EXISTS documents_doc_type ON documents (doc_type);
                CREATE TABLE IF NOT EXISTS vector_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            """)
            cur = await conn.execute(
                "SELECT atttypmod FROM pg_attribute WHERE attrelid = 'chunks'::regclass AND attname = 'embedding'"
            )
            row = await cur.fetchone()
            if row and row[0] != d:
                raise RuntimeError(
                    f"pgvector column has dimension {row[0]} but EMBEDDING_DIM={d}. "
                    "Drop the chunks/company_embeddings tables or restore the previous embedding settings."
                )
            await conn.execute(
                "INSERT INTO vector_meta (key, value) VALUES ('embedding_model', %s) ON CONFLICT (key) DO NOTHING",
                (self.model_name,),
            )
            cur = await conn.execute("SELECT value FROM vector_meta WHERE key = 'embedding_model'")
            stored = (await cur.fetchone())[0]
            if stored != self.model_name:
                cur = await conn.execute("SELECT count(*) FROM chunks")
                if (await cur.fetchone())[0] > 0:
                    raise RuntimeError(
                        f"Stored vectors were embedded with '{stored}' but the configured model is "
                        f"'{self.model_name}'. Re-embed with: python -m app.ingestion.reindex"
                    )
                await self.set_model_name(conn)

    async def set_model_name(self, conn=None) -> None:
        sql = ("INSERT INTO vector_meta (key, value) VALUES ('embedding_model', %s) "
               "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value")
        if conn is not None:
            await conn.execute(sql, (self.model_name,))
            return
        async with self.pool.connection() as c:
            await c.execute(sql, (self.model_name,))

    async def has_document(self, doc_key: str) -> bool:
        async with self.pool.connection() as conn:
            cur = await conn.execute("SELECT 1 FROM documents WHERE doc_key = %s", (doc_key,))
            return await cur.fetchone() is not None

    async def add_document(self, doc: Document, chunks: list[str], embeddings: list[list[float]]) -> int | None:
        """Insert a document with its chunk embeddings. Returns None if it already exists."""
        async with self.pool.connection() as conn, conn.transaction():
            cur = await conn.execute(
                """INSERT INTO documents (doc_key, doc_type, title, content, source, source_url,
                                              published_at, company_ids, sentiment)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                       ON CONFLICT (doc_key) DO NOTHING RETURNING id""",
                (doc.doc_key, doc.doc_type, doc.title, doc.content, doc.source, doc.source_url,
                 doc.published_at, doc.company_ids, doc.sentiment),
            )
            row = await cur.fetchone()
            if row is None:
                return None
            doc_id = row[0]
            async with conn.cursor() as c:
                await c.executemany(
                    "INSERT INTO chunks (document_id, chunk_index, content, embedding) VALUES (%s,%s,%s,%s)",
                    [(doc_id, i, ch, np.asarray(emb, dtype=np.float32)) for i, (ch, emb) in
                     enumerate(zip(chunks, embeddings))],
                )
            return doc_id

    async def search(self, query_embedding: list[float], k: int = 6, doc_types: list[str] | None = None,
                     company_ids: list[str] | None = None) -> list[dict[str, Any]]:
        where, params = [], []
        if doc_types:
            where.append("d.doc_type = ANY(%s)")
            params.append(doc_types)
        if company_ids:
            where.append("d.company_ids && %s")
            params.append(company_ids)
        clause = f"WHERE {' AND '.join(where)}" if where else ""
        q = np.asarray(query_embedding, dtype=np.float32)
        sql = f"""
            SELECT d.id AS document_id, d.doc_type, d.title, d.source, d.source_url, d.published_at,
                   d.company_ids, d.sentiment, c.content, 1 - (c.embedding <=> %s) AS score
            FROM chunks c JOIN documents d ON d.id = c.document_id
            {clause}
            ORDER BY c.embedding <=> %s
            LIMIT %s
        """
        async with self.pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(sql, [q, *params, q, k * 3])
            rows = await cur.fetchall()
        # keep the best chunk per document
        seen, out = set(), []
        for r in rows:
            if r["document_id"] in seen:
                continue
            seen.add(r["document_id"])
            r["score"] = float(r["score"])
            r["published_at"] = r["published_at"].isoformat() if r["published_at"] else None
            out.append(r)
            if len(out) >= k:
                break
        return out

    async def upsert_company_embedding(self, company_id: str, embedding: list[float]) -> None:
        async with self.pool.connection() as conn:
            await conn.execute(
                """INSERT INTO company_embeddings (company_id, embedding) VALUES (%s, %s)
                   ON CONFLICT (company_id) DO UPDATE SET embedding = EXCLUDED.embedding, updated_at = now()""",
                (company_id, np.asarray(embedding, dtype=np.float32)),
            )

    async def company_similarity(self, company_id: str, candidate_ids: list[str] | None = None) -> dict[str, float]:
        """Cosine similarity between a company's embedding and all (or the given) companies."""
        sql = """
            SELECT o.company_id, 1 - (o.embedding <=> t.embedding) AS score
            FROM company_embeddings t JOIN company_embeddings o ON o.company_id <> t.company_id
            WHERE t.company_id = %s
        """
        params: list[Any] = [company_id]
        if candidate_ids is not None:
            sql += " AND o.company_id = ANY(%s)"
            params.append(candidate_ids)
        async with self.pool.connection() as conn:
            cur = await conn.execute(sql, params)
            return {cid: float(score) for cid, score in await cur.fetchall()}

    async def news_sentiment(self, company_ids: list[str]) -> dict[str, tuple[float, int]]:
        """Average sentiment and article count of news mentioning each company."""
        async with self.pool.connection() as conn:
            cur = await conn.execute(
                """SELECT cid, avg(sentiment)::float, count(*)
                   FROM documents, unnest(company_ids) AS cid
                   WHERE doc_type = 'news' AND sentiment IS NOT NULL AND cid = ANY(%s)
                   GROUP BY cid""",
                (company_ids,),
            )
            return {cid: (avg, n) for cid, avg, n in await cur.fetchall()}

    async def counts(self) -> dict[str, int]:
        async with self.pool.connection() as conn:
            cur = await conn.execute("SELECT doc_type, count(*) FROM documents GROUP BY doc_type")
            out = {t: n for t, n in await cur.fetchall()}
            cur = await conn.execute("SELECT count(*) FROM chunks")
            out["chunks"] = (await cur.fetchone())[0]
            return out
