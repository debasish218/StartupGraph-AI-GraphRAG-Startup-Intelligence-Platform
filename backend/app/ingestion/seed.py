"""Load the curated seed dataset into Neo4j and pgvector.

Usage:  python -m app.ingestion.seed
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import date
from pathlib import Path
from typing import Any

from app.container import Container
from app.db.vector_store import Document
from app.services.sentiment import score_sentiment
from app.utils import format_usd, slugify

log = logging.getLogger(__name__)

SEED_DIR = Path(__file__).resolve().parents[2] / "data" / "seed"


def load_json(name: str) -> Any:
    return json.loads((SEED_DIR / name).read_text())


def company_profile_text(c: dict[str, Any]) -> str:
    parts = [f"{c['name']}: {c['description']}", f"Sector: {c['sector']}."]
    if c.get("tags"):
        parts.append(f"Focus areas: {', '.join(c['tags'])}.")
    if c.get("technologies"):
        parts.append(f"Technologies: {', '.join(c['technologies'])}.")
    parts.append(f"Founded {c.get('founded_year')} in {c.get('country')}, about {c.get('employee_count')} employees.")
    return " ".join(parts)


def funding_report_text(r: dict[str, Any], names: dict[str, str]) -> str:
    company = names.get(r["company"], r["company"])
    leads = [names.get(i, i) for i in r.get("lead_investors") or []]
    others = [names.get(i, i) for i in r.get("investors") or []]
    text = f"{company} raised {format_usd(r.get('amount'))} in a {r['round_type']} round on {r['date']}."
    if leads:
        text += f" The round was led by {', '.join(leads)}."
    if others:
        text += f" Participating investors included {', '.join(others)}."
    return text


async def embed_and_store(container: Container, docs: list[Document]) -> int:
    from app.db.vector_store import chunk_text

    added = 0
    for doc in docs:
        if await container.vectors.has_document(doc.doc_key):
            continue
        chunks = chunk_text(doc.content)
        embeddings = await asyncio.to_thread(
            container.embedder.embed_documents, [f"{doc.title}. {ch}" for ch in chunks]
        )
        if await container.vectors.add_document(doc, chunks, embeddings) is not None:
            added += 1
    return added


async def load_seed(container: Container) -> dict[str, int]:
    companies = load_json("companies.json")
    investors = load_json("investors.json")
    founders = load_json("founders.json")
    rounds = load_json("funding_rounds.json")
    rel = load_json("relationships.json")
    documents = load_json("documents.json")

    w = container.writer
    await w.upsert_technologies(rel["technologies"])
    await w.upsert_companies(companies)
    await w.upsert_investors(investors)
    await w.upsert_founders(founders)
    await w.add_funding_rounds(rounds)
    await w.refresh_investment_aggregates()
    await w.add_competitors(rel["competes_with"])
    await w.add_partnerships(rel["partners_with"])
    await w.add_acquisitions(rel["acquisitions"])

    names = {c["id"]: c["name"] for c in companies} | {i["id"]: i["name"] for i in investors}
    docs: list[Document] = []
    for c in companies:
        docs.append(Document(doc_type="company_profile", title=f"{c['name']} company profile",
                             content=company_profile_text(c), company_ids=[c["id"]], source="seed",
                             source_url=c.get("website")))
    for r in rounds:
        docs.append(Document(
            doc_type="funding_report", title=f"{names.get(r['company'], r['company'])} {r['round_type']} funding",
            content=funding_report_text(r, names),
            company_ids=[r["company"], *(r.get("lead_investors") or []), *(r.get("investors") or [])],
            published_at=date.fromisoformat(r["date"]), source="seed",
        ))
    for d in documents:
        docs.append(Document(
            doc_type=d["doc_type"], title=d["title"], content=d["content"], company_ids=d["companies"],
            published_at=date.fromisoformat(d["published_at"]), source="seed",
            sentiment=score_sentiment(d["content"]) if d["doc_type"] == "news" else None,
        ))
        if d["doc_type"] == "news":
            await w.add_article(f"news-{slugify(d['title'])[:80]}", d["title"], d["published_at"], None,
                                None, d["companies"])

    added = await embed_and_store(container, docs)

    profile_texts = [company_profile_text(c) for c in companies]
    vectors = await asyncio.to_thread(container.embedder.embed_documents, profile_texts)
    for c, v in zip(companies, vectors):
        await container.vectors.upsert_company_embedding(c["id"], v)

    await container.refresh_catalog()
    stats = {"companies": len(companies), "investors": len(investors), "founders": len(founders),
             "funding_rounds": len(rounds), "documents_added": added}
    log.info("Seed load complete: %s", stats)
    return stats


async def _main() -> None:
    logging.basicConfig(level=logging.INFO)
    container = Container.from_settings()
    await container.start()
    try:
        print(await load_seed(container))
    finally:
        await container.stop()


if __name__ == "__main__":
    asyncio.run(_main())
