"""News intelligence pipeline and external source connectors.

    article -> event detection -> graph updates (MERGE) -> NewsArticle + MENTIONED_IN
            -> sentiment -> chunk + embed -> pgvector

Connectors: RSS feeds, the Y Combinator directory (yc-oss public API), GitHub
organisations, and CSV exports (e.g. a Crunchbase export you are licensed to use).
LinkedIn and Crunchbase are not scraped directly: their terms prohibit it.
"""

from __future__ import annotations

import asyncio
import csv
import html
import io
import logging
import re
from datetime import UTC, date, datetime
from typing import TYPE_CHECKING, Any

import feedparser
import httpx

from app.agents.entities import infer_topics
from app.db.vector_store import Document
from app.ingestion.events import Event, extract_events
from app.ingestion.seed import embed_and_store
from app.services.sentiment import score_sentiment
from app.utils import slugify

if TYPE_CHECKING:
    from app.container import Container

log = logging.getLogger(__name__)
USER_AGENT = "StartupGraphAI/1.0 (+https://github.com/debasish218/StartupGraph-AI-GraphRAG-Startup-Intelligence-Platform)"


def strip_html(text: str) -> str:
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", text or "")).split())


class NewsPipeline:
    def __init__(self, container: Container):
        self.c = container

    async def _apply_event(self, ev: Event, published: str, text: str = "") -> dict[str, Any] | None:
        w = self.c.writer
        if not ev.company:
            return None
        # Companies first seen in the news get sector tags inferred from the article.
        topics = infer_topics(text)
        new_company_props = {"tags": topics, "sector": topics[0] if topics else None}
        if ev.type == "funding":
            cid = await w.ensure_company(ev.company, **new_company_props)
            leads = [await w.ensure_investor(n) for n in ev.lead_investors]
            others = [await w.ensure_investor(n) for n in ev.investors]
            await w.add_funding_rounds([{
                "company": cid, "round_type": ev.round_type or "Undisclosed", "amount": ev.amount,
                "date": published, "lead_investors": leads, "investors": others, "source": "news",
            }])
            await w.refresh_investment_aggregates()
            return {"type": "funding", "company": cid, "amount": ev.amount, "round_type": ev.round_type,
                    "investors": leads + others}
        if ev.type == "acquisition" and ev.counterparty:
            a, b = await w.ensure_company(ev.company), await w.ensure_company(ev.counterparty)
            await w.add_acquisitions([{"acquirer": a, "target": b, "date": published, "amount": ev.amount}])
            return {"type": "acquisition", "acquirer": a, "target": b, "amount": ev.amount}
        if ev.type == "partnership" and ev.counterparty:
            a, b = await w.ensure_company(ev.company), await w.ensure_company(ev.counterparty)
            await w.add_partnerships([{"a": a, "b": b, "since": int(published[:4]), "description": ev.evidence[:200]}])
            return {"type": "partnership", "a": a, "b": b}
        if ev.type == "product_launch":
            cid = await w.ensure_company(ev.company)
            await self.c.graph.write(
                "MATCH (c:Entity {id: $id}) SET c.last_product_launch = $product, c.last_launch_date = date($d)",
                {"id": cid, "product": ev.product, "d": published},
            )
            return {"type": "product_launch", "company": cid, "product": ev.product}
        return None

    async def process_article(self, title: str, body: str, url: str | None = None,
                              published_at: date | None = None, source: str = "news",
                              apply_events: bool = True) -> dict[str, Any]:
        published = (published_at or date.today()).isoformat()
        doc = Document(doc_type="news", title=title, content=body or title, company_ids=[], source=source,
                       source_url=url, published_at=published_at or date.today())
        if await self.c.vectors.has_document(doc.doc_key):
            return {"status": "duplicate", "title": title}

        events = await extract_events(title, body, self.c.llm)
        applied = []
        if apply_events:
            for ev in events:
                try:
                    if res := await self._apply_event(ev, published, f"{title}. {body}"):
                        applied.append(res)
                except Exception as exc:  # noqa: BLE001 - one bad event must not drop the article
                    log.warning("Failed to apply event %s: %s", ev, exc)
        if applied:
            await self.c.refresh_catalog()

        text = f"{title}. {body}"
        mentioned = {e.id for e, _, _ in self.c.catalog.find_mentions(text)}
        for a in applied:
            mentioned.update(v for k, v in a.items() if k in ("company", "acquirer", "target", "a", "b") and v)
            mentioned.update(a.get("investors") or [])
        doc.company_ids = sorted(mentioned)
        doc.sentiment = score_sentiment(text)

        article_id = f"news-{doc.doc_key[:16]}"
        await self.c.writer.add_article(article_id, title, published, url,
                                        events[0].type if events else None, doc.company_ids)
        await embed_and_store(self.c, [doc])
        return {"status": "ingested", "title": title, "events": [e.to_dict() for e in events],
                "graph_updates": applied, "mentions": doc.company_ids, "sentiment": doc.sentiment}

    async def ingest_rss(self, feeds: list[str] | None = None, max_items: int = 30) -> dict[str, Any]:
        feeds = feeds or self.c.settings.rss_feed_list
        results: list[dict[str, Any]] = []
        async with httpx.AsyncClient(timeout=20, headers={"User-Agent": USER_AGENT}, follow_redirects=True) as client:
            for feed_url in feeds:
                try:
                    resp = await client.get(feed_url)
                    resp.raise_for_status()
                except httpx.HTTPError as exc:
                    log.warning("RSS fetch failed for %s: %s", feed_url, exc)
                    results.append({"feed": feed_url, "status": "error", "error": str(exc)})
                    continue
                parsed = await asyncio.to_thread(feedparser.parse, resp.content)
                for entry in parsed.entries[:max_items]:
                    published = None
                    if getattr(entry, "published_parsed", None):
                        published = datetime(*entry.published_parsed[:6], tzinfo=UTC).date()
                    body = strip_html(entry.get("summary", "") or entry.get("description", ""))
                    try:
                        res = await self.process_article(strip_html(entry.get("title", "")), body,
                                                         entry.get("link"), published, source=feed_url)
                    except Exception as exc:  # noqa: BLE001
                        log.warning("Failed to ingest %s: %s", entry.get("link"), exc)
                        res = {"status": "error", "title": entry.get("title"), "error": str(exc)}
                    results.append(res)
        summary = {
            "ingested": sum(r.get("status") == "ingested" for r in results),
            "duplicates": sum(r.get("status") == "duplicate" for r in results),
            "errors": sum(r.get("status") == "error" for r in results),
            "graph_updates": sum(len(r.get("graph_updates") or []) for r in results),
            "items": [r for r in results if r.get("status") != "duplicate"][:50],
        }
        log.info("RSS ingestion: %s", {k: v for k, v in summary.items() if k != "items"})
        return summary


def _batch_date(batch: str | None) -> str | None:
    """'Summer 2020' -> '2020-06-01', 'W21' -> '2021-01-01'."""
    if not batch:
        return None
    seasons = {"winter": "01", "spring": "04", "summer": "06", "fall": "09", "autumn": "09",
               "w": "01", "x": "04", "s": "06", "f": "09"}
    if m := re.match(r"(winter|spring|summer|fall|autumn)\s+(\d{4})", batch, re.I):
        return f"{m.group(2)}-{seasons[m.group(1).lower()]}-01"
    if m := re.match(r"([WXSF])(\d{2})$", batch.strip(), re.I):
        return f"20{m.group(2)}-{seasons[m.group(1).lower()]}-01"
    return None


async def import_yc_companies(c: Container, industry: str | None = None, tag: str | None = None,
                              batch: str | None = None, limit: int = 200) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=60, headers={"User-Agent": USER_AGENT}) as client:
        resp = await client.get(c.settings.yc_directory_url)
        resp.raise_for_status()
        companies = resp.json()

    def keep(x: dict[str, Any]) -> bool:
        if x.get("status") not in ("Active", "Public"):
            return False
        if industry and industry.lower() not in " ".join(x.get("industries") or []).lower():
            return False
        if tag and tag.lower() not in [t.lower() for t in x.get("tags") or []]:
            return False
        return not batch or (x.get("batch") or "").lower() == batch.lower()

    selected = [x for x in companies if keep(x)][:limit]
    w = c.writer
    rows, rounds, docs = [], [], []
    for x in selected:
        cid = await w.ensure_company(x["name"])
        industries = x.get("industries") or []
        rows.append({
            "id": cid, "name": x["name"], "aliases": x.get("former_names") or [],
            "description": x.get("long_description") or x.get("one_liner") or "",
            "sector": industries[-1] if industries else x.get("industry"), "tags": x.get("tags") or [],
            "country": (x.get("regions") or [None])[0], "employee_count": x.get("team_size"),
            "website": x.get("website"), "is_startup": True, "source": "yc",
            "founded_year": int(_batch_date(x.get("batch"))[:4]) if _batch_date(x.get("batch")) else None,
        })
        if d := _batch_date(x.get("batch")):
            rounds.append({"company": cid, "round_type": "Accelerator", "amount": 500000, "date": d,
                           "lead_investors": ["y-combinator"], "investors": [], "source": "yc"})
        docs.append(Document(doc_type="company_profile", title=f"{x['name']} company profile",
                             content=f"{x['name']}: {x.get('one_liner') or ''}. {x.get('long_description') or ''} "
                                     f"Tags: {', '.join(x.get('tags') or [])}. YC batch {x.get('batch')}.",
                             company_ids=[cid], source="yc", source_url=x.get("url")))
    if rows:
        # Only fill fields for companies we did not already curate.
        await c.graph.write("""
            UNWIND $rows AS row
            MERGE (n:Entity {id: row.id})
            SET n:Company, n.is_startup = true,
                n.name = coalesce(n.name, row.name), n.description = coalesce(n.description, row.description),
                n.sector = coalesce(n.sector, row.sector), n.tags = coalesce(n.tags, row.tags),
                n.country = coalesce(n.country, row.country), n.website = coalesce(n.website, row.website),
                n.employee_count = coalesce(row.employee_count, n.employee_count),
                n.founded_year = coalesce(n.founded_year, row.founded_year), n.source = coalesce(n.source, 'yc'),
                n.aliases = coalesce(n.aliases, row.aliases),
                n.aliases_text = reduce(s = '', a IN coalesce(n.aliases, row.aliases) | s + ' ' + a)
        """, {"rows": rows})
        await c.graph.write("MERGE (y:Entity {id: 'y-combinator'}) ON CREATE SET y:Investor, y.name = 'Y Combinator', "
                            "y.type = 'Accelerator', y.quality = 0.86")
        await w.add_funding_rounds(rounds)
        await w.refresh_investment_aggregates()
        added = await embed_and_store(c, docs)
        profile_vectors = await asyncio.to_thread(c.embedder.embed_documents, [d.content for d in docs])
        for d, v in zip(docs, profile_vectors):
            await c.vectors.upsert_company_embedding(d.company_ids[0], v)
        await c.refresh_catalog()
    else:
        added = 0
    return {"imported": len(rows), "documents_added": added}


async def enrich_github(c: Container) -> dict[str, Any]:
    res = await c.graph.read("MATCH (c:Company) WHERE c.github_org IS NOT NULL RETURN c.id AS id, c.github_org AS org")
    headers = {"User-Agent": USER_AGENT, "Accept": "application/vnd.github+json"}
    if c.settings.github_token:
        headers["Authorization"] = f"Bearer {c.settings.github_token}"
    updated, errors = 0, []
    async with httpx.AsyncClient(timeout=20, headers=headers) as client:
        for row in res.rows:
            try:
                org = (await client.get(f"https://api.github.com/orgs/{row['org']}")).raise_for_status().json()
                repos = (await client.get(f"https://api.github.com/orgs/{row['org']}/repos",
                                          params={"per_page": 100, "sort": "pushed"})).raise_for_status().json()
                stars = sum(r.get("stargazers_count", 0) for r in repos)
                top = sorted(repos, key=lambda r: r.get("stargazers_count", 0), reverse=True)[:3]
                await c.graph.write(
                    """MATCH (c:Entity {id: $id})
                       SET c.github_public_repos = $repos, c.github_followers = $followers,
                           c.github_stars = $stars, c.github_top_repos = $top, c.github_synced_at = datetime()""",
                    {"id": row["id"], "repos": org.get("public_repos"), "followers": org.get("followers"),
                     "stars": stars, "top": [r["name"] for r in top]},
                )
                updated += 1
            except httpx.HTTPError as exc:
                errors.append(f"{row['org']}: {exc}")
                if "403" in str(exc) or "429" in str(exc):
                    break  # rate limited; set GITHUB_TOKEN for higher limits
    return {"updated": updated, "errors": errors}


CSV_FIELDS = {
    "name": ["name", "organization name", "company", "company name"],
    "description": ["description", "short description", "full description"],
    "sector": ["sector", "industry", "industries", "category"],
    "country": ["country", "headquarters location", "hq country"],
    "website": ["website", "homepage url", "url"],
    "founded_year": ["founded_year", "founded date", "founded"],
    "employee_count": ["employee_count", "number of employees", "employees"],
    "round_type": ["round_type", "funding type", "last funding type"],
    "amount": ["amount", "money raised", "last funding amount", "money raised (in usd)"],
    "date": ["date", "announced date", "last funding date"],
    "investors": ["investors", "lead investors", "top 5 investors"],
}


async def import_csv(c: Container, content: str) -> dict[str, Any]:
    """Import companies (and optionally one funding round per row) from a CSV export."""
    reader = csv.DictReader(io.StringIO(content))
    header = {h.lower().strip(): h for h in reader.fieldnames or []}
    col = {k: next((header[a] for a in aliases if a in header), None) for k, aliases in CSV_FIELDS.items()}
    if not col["name"]:
        raise ValueError(f"CSV needs a company name column (one of {CSV_FIELDS['name']})")

    def get(row: dict[str, str], key: str) -> str | None:
        if not col[key]:
            return None
        return (row.get(col[key]) or "").strip() or None

    companies, rounds = [], []
    for row in reader:
        name = get(row, "name")
        if not name:
            continue
        cid = await c.writer.ensure_company(name)
        year = re.search(r"\d{4}", get(row, "founded_year") or "")
        employees = re.findall(r"\d+", (get(row, "employee_count") or "").replace(",", ""))
        companies.append({
            "id": cid, "name": name, "description": get(row, "description"), "sector": get(row, "sector"),
            "country": get(row, "country"), "website": get(row, "website"), "source": "csv", "is_startup": True,
            "founded_year": int(year.group()) if year else None,
            "employee_count": int(employees[-1]) if employees else None,
        })
        amount_raw = re.sub(r"[^\d.]", "", get(row, "amount") or "")
        round_date = get(row, "date")
        if amount_raw and round_date and re.match(r"\d{4}-\d{2}-\d{2}", round_date):
            investors = [await c.writer.ensure_investor(n.strip())
                         for n in re.split(r"[,;]", get(row, "investors") or "") if n.strip()]
            rounds.append({"company": cid, "round_type": get(row, "round_type") or "Undisclosed",
                           "amount": float(amount_raw), "date": round_date[:10], "lead_investors": investors[:1],
                           "investors": investors[1:], "source": "csv"})
    await c.writer.upsert_companies(companies)
    if rounds:
        await c.writer.add_funding_rounds(rounds)
        await c.writer.refresh_investment_aggregates()
    docs = [Document(doc_type="company_profile", title=f"{x['name']} company profile",
                     content=f"{x['name']}: {x['description'] or ''} Sector: {x['sector'] or 'n/a'}.",
                     company_ids=[x["id"]], source="csv", source_url=x["website"])
            for x in companies if x["description"]]
    added = await embed_and_store(c, docs)
    await c.refresh_catalog()
    return {"companies": len(companies), "funding_rounds": len(rounds), "documents_added": added,
            "slugs": [slugify(x["name"]) for x in companies][:20]}
