"""Re-embed every chunk and company profile with the configured embedding model.

Usage:  python -m app.ingestion.reindex
Run after changing EMBEDDING_PROVIDER / EMBEDDING_MODEL (same EMBEDDING_DIM). To change the
dimension, drop the `chunks` and `company_embeddings` tables first; they are recreated on start.
"""

import asyncio
import logging

import numpy as np

from app.container import Container

BATCH = 64


async def reindex(c: Container) -> dict[str, int]:
    async with c.vectors.pool.connection() as conn:
        cur = await conn.execute(
            "SELECT c.id, d.title, c.content FROM chunks c JOIN documents d ON d.id = c.document_id ORDER BY c.id")
        chunks = await cur.fetchall()
        cur = await conn.execute(
            "SELECT company_ids[1], content FROM documents WHERE doc_type = 'company_profile' "
            "AND cardinality(company_ids) > 0 ORDER BY created_at")
        profiles = dict(await cur.fetchall())  # latest profile per company wins

    for i in range(0, len(chunks), BATCH):
        batch = chunks[i:i + BATCH]
        vectors = await asyncio.to_thread(c.embedder.embed_documents, [f"{t}. {txt}" for _, t, txt in batch])
        async with c.vectors.pool.connection() as conn, conn.cursor() as cur:
            await cur.executemany("UPDATE chunks SET embedding = %s WHERE id = %s",
                                  [(np.asarray(v, dtype=np.float32), cid) for (cid, _, _), v in zip(batch, vectors)])
    ids = list(profiles)
    for i in range(0, len(ids), BATCH):
        batch = ids[i:i + BATCH]
        vectors = await asyncio.to_thread(c.embedder.embed_documents, [profiles[x] for x in batch])
        for cid, v in zip(batch, vectors):
            await c.vectors.upsert_company_embedding(cid, v)
    await c.vectors.set_model_name()
    return {"chunks": len(chunks), "companies": len(ids)}


async def _main() -> None:
    logging.basicConfig(level=logging.INFO)
    c = Container.from_settings()
    await c.start(check_embedding_model=False)
    try:
        print(f"Re-embedded with {c.embedder.name}: {await reindex(c)}")
    finally:
        await c.stop()


if __name__ == "__main__":
    asyncio.run(_main())
