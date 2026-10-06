"""Remove an entity (and its funding rounds / news links) from both stores.

Usage: python -m scripts.delete_entity <entity-id> [--doc-url URL ...]
"""

import asyncio
import sys

from app.container import Container


async def main(entity_id: str, doc_urls: list[str]) -> None:
    c = Container.from_settings()
    await c.start()
    try:
        await c.graph.write(
            """MATCH (e:Entity {id: $id})
               OPTIONAL MATCH (e)-[:RAISED]->(r:FundingRound)
               OPTIONAL MATCH (e)-[:MENTIONED_IN]->(n:NewsArticle)
               WHERE NOT EXISTS { MATCH (o)-[:MENTIONED_IN]->(n) WHERE o <> e }
               WITH e, collect(DISTINCT r) + collect(DISTINCT n) AS owned
               FOREACH (x IN owned | DETACH DELETE x)
               DETACH DELETE e""", {"id": entity_id})
        if doc_urls:
            await c.graph.write("MATCH (n:NewsArticle) WHERE n.url IN $urls DETACH DELETE n", {"urls": doc_urls})
        await c.writer.refresh_investment_aggregates()
        async with c.vectors.pool.connection() as conn:
            await conn.execute("DELETE FROM company_embeddings WHERE company_id = %s", (entity_id,))
            for url in doc_urls:
                await conn.execute("DELETE FROM documents WHERE source_url = %s", (url,))
        print(f"deleted {entity_id}")
    finally:
        await c.stop()


if __name__ == "__main__":
    args = sys.argv[1:]
    urls = args[args.index("--doc-url") + 1:] if "--doc-url" in args else []
    asyncio.run(main(args[0], urls))
