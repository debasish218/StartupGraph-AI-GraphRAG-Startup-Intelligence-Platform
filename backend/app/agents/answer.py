"""Answer Generation Agent (Agent 6): context building, explainable answers, confidence."""

from __future__ import annotations

import json
from typing import Any

from app.utils import format_usd

MAX_CONTEXT_ROWS = 30
MAX_ITEMS = 12


# ------------------------------------------------------------------ helpers

def _is_graph_element(v: Any) -> bool:
    return isinstance(v, dict) and ("labels" in v or ("source" in v and "target" in v and "type" in v)
                                    or "path" in v)


def scalar_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Strip node/relationship/path values from rows, keeping readable columns."""
    out = []
    for row in rows:
        clean = {}
        for k, v in row.items():
            if _is_graph_element(v):
                continue
            if isinstance(v, list) and v and all(_is_graph_element(x) for x in v):
                continue
            clean[k] = v
        if clean:
            out.append(clean)
    return out


def extract_paths(rows: list[dict[str, Any]], limit: int = 15) -> list[str]:
    paths: list[str] = []

    def visit(v: Any) -> None:
        if isinstance(v, dict) and "path" in v and "text" in v:
            if v["text"] not in paths:
                paths.append(v["text"])
        elif isinstance(v, list):
            for x in v:
                visit(x)

    for row in rows:
        for v in row.values():
            visit(v)
    return paths[:limit]


def _names(xs: list[Any] | None, n: int = 5) -> str:
    xs = [x for x in (xs or []) if x]
    if not xs:
        return "none recorded"
    return ", ".join(map(str, xs[:n])) + (f" (+{len(xs) - n} more)" if len(xs) > n else "")


def _subject(entities: dict[str, Any], key: str = "companies") -> str:
    group = entities.get(key) or []
    return " and ".join(e["name"] for e in group) if group else "the selected entity"


def _topic_label(entities: dict[str, Any]) -> str:
    parts = list(entities.get("topics") or []) + [t["name"] for t in entities.get("technologies") or []]
    return "/".join(parts)


def _doc_ref(documents: list[dict[str, Any]], company_ids: list[str] | None = None, n: int = 2) -> str:
    refs = []
    for i, d in enumerate(documents, 1):
        if company_ids is None or set(d.get("company_ids") or []) & set(company_ids):
            refs.append(f"[D{i}]")
        if len(refs) >= n:
            break
    return " " + " ".join(refs) if refs else ""


# ------------------------------------------------------------ rule answers

def compose_answer(state: dict[str, Any]) -> str:
    """Deterministic, explainable answer used when no LLM is configured (or it fails)."""
    intent = state["intent"]
    ents = state.get("entities") or {}
    rows = scalar_rows((state.get("graph") or {}).get("rows") or [])
    docs = state.get("documents") or []
    rankings = state.get("rankings") or []
    similar = state.get("similar") or []
    paths = state.get("paths") or []
    notes = state.get("notes") or []
    lines: list[str] = []
    topic = _topic_label(ents)

    def bullet(text: str) -> None:
        lines.append(f"- {text}")

    if intent == "competitors" and rows:
        lines.append(f"**Competitors of {_subject(ents)}** ({len(rows)} in the knowledge graph) [G]:")
        for r in rows[:MAX_ITEMS]:
            bullet(f"**{r['competitor']}** ({r.get('sector') or 'n/a'}) — total funding "
                   f"{format_usd(r.get('total_funding'))}; investors: {_names(r.get('investors'))}")
    elif intent == "competitor_investors" and rows:
        lines.append(f"**Investors backing competitors of {_subject(ents)}** [G]:")
        for r in rows[:MAX_ITEMS]:
            bullet(f"**{r['investor']}** ({r.get('investor_type') or 'investor'}) funds "
                   f"{r['competitors_count']} competitor(s): {_names(r['competitors_funded'], 6)}")
    elif intent == "investors_of" and rows:
        lines.append(f"**Investors in {_subject(ents)}** [G]:")
        for r in rows[:MAX_ITEMS]:
            lead = " — lead investor" if r.get("lead") else ""
            bullet(f"**{r['investor']}** ({r.get('investor_type') or 'investor'}), {r.get('rounds') or 0} "
                   f"round(s), last {r.get('last_round') or 'n/a'}{lead}")
    elif intent == "active_investors" and rows:
        label = f"{topic} startups" if topic else "startups"
        lines.append(f"**Most active investors in {label}** (by number of startups backed) [G]:")
        for r in rows[:MAX_ITEMS]:
            bullet(f"**{r['investor']}** ({r.get('investor_type') or 'investor'}) — backed "
                   f"{r['startups_backed']} startup(s), led {r.get('rounds_led') or 0} round(s): "
                   f"{_names(r.get('portfolio'), 6)}")
    elif intent == "investor_portfolio" and rows:
        lines.append(f"**Portfolio of {_subject(ents, 'investors')}** [G]:")
        for r in rows[:MAX_ITEMS]:
            lead = " (lead)" if r.get("lead") else ""
            bullet(f"**{r['company']}** — {r.get('sector') or 'n/a'}, company total funding "
                   f"{format_usd(r.get('company_total_funding'))}{lead}")
    elif intent == "founder_background" and rows:
        employers = _subject(ents, "employers")
        label = f"{topic} startups" if topic else "Startups"
        lines.append(f"**{label} founded by former {employers} people** [G]:")
        for r in rows[:MAX_ITEMS]:
            bullet(f"**{r['company']}** ({r.get('sector') or 'n/a'}) — founders {_names(r['founders'])} "
                   f"previously at {_names(r['former_employers'])}; total funding {format_usd(r.get('total_funding'))}")
    elif intent == "founders_of" and rows:
        lines.append("**Founders** [G]:")
        for r in rows[:MAX_ITEMS]:
            prev = f"; previously at {_names(r.get('previous_employers'))}" if r.get("previous_employers") else ""
            bullet(f"**{r['founder']}** — co-founder of {r['company']}{prev}")
    elif intent == "funding_search" and rows:
        lines.append(f"**Matching funding rounds** ({len(rows)}) [G]:")
        for r in rows[:MAX_ITEMS]:
            bullet(f"**{r['company']}** ({r.get('sector') or 'n/a'}) raised {format_usd(r.get('amount'))} "
                   f"{r['round_type']} on {r['date']}; investors: {_names(r.get('investors'))}")
    elif intent == "acquisitions" and rows:
        lines.append("**Acquisitions** [G]:")
        for r in rows[:MAX_ITEMS]:
            bullet(f"**{r['acquirer']}** acquired **{r['target']}** ({r.get('date') or 'date n/a'}, "
                   f"{format_usd(r.get('amount'))})")
    elif intent == "technology_users" and rows:
        lines.append(f"**Companies using {_subject(ents, 'technologies')}** [G]:")
        for r in rows[:MAX_ITEMS]:
            bullet(f"**{r['company']}** ({r.get('sector') or 'n/a'}), total funding "
                   f"{format_usd(r.get('total_funding'))}")
    elif intent == "relationship" and (rows or paths):
        names = [e["name"] for e in ents.get("companies", []) + ents.get("investors", []) + ents.get("founders", [])]
        lines.append(f"**How {', '.join(names)} are connected** [G]:")
        direct = [r for r in rows if "relationship" in r]
        if direct:
            lines.append("Direct relationships:")
            for r in direct[:MAX_ITEMS * 2]:
                bullet(f"{r['from']} **{r['relationship']}** {r['to']}{_rel_detail(r.get('details'))}")
        indirect = [p for p in paths if p.count("-[") > 1]
        if indirect:
            lines.append("Indirect connections:")
            for p in indirect[:MAX_ITEMS]:
                bullet(p)
    elif intent == "similar_companies" and similar:
        target = _subject(ents)
        suffix = " with no investors in common" if state.get("different_investors") else ""
        lines.append(f"**Companies most similar to {target}{suffix}** (embedding + technology + investor + "
                     "sector similarity):")
        for s in similar[:10]:
            why = []
            if s["shared_technologies"]:
                why.append(f"shared tech: {_names(s['shared_technologies'], 4)}")
            if s["shared_investors"]:
                why.append(f"shared investors: {_names(s['shared_investors'], 4)}")
            if not state.get("different_investors") or not s["shared_investors"]:
                why.append(f"investors: {_names(s['investors'], 3)}")
            bullet(f"**{s['name']}** — similarity {s['score']:.2f} ({s['sector']}); {'; '.join(why)}")
    elif intent == "compare" and rows:
        lines.append(f"**Comparison of {_subject(ents)}** [G]:")
        scores = {r["company_id"]: r for r in rankings}
        for r in rows:
            if "name" not in r or "founders" not in r:
                continue
            sc = scores.get(r["id"])
            score_txt = f"; startup score {sc['score']:.2f}" if sc else ""
            bullet(f"**{r['name']}** — {r.get('sector')}, founded {r.get('founded_year')}, ~{r.get('employees')} "
                   f"employees, total funding {format_usd(r.get('total_funding'))}{score_txt}. "
                   f"Investors: {_names(r.get('investors'), 4)}. Technologies: {_names(r.get('technologies'), 4)}."
                   f"{_doc_ref(docs, [r['id']], 1)}")
        common = state.get("in_common") or {}
        for key, vals in common.items():
            if vals:
                bullet(f"In common — {key}: {_names(vals, 6)}")
        direct = [p for p in paths if p.count("-[") == 1]
        if direct:
            bullet("Direct links: " + "; ".join(direct[:4]))
    elif intent == "recommendation" and rankings:
        label = f"{topic} startups" if topic else "startups"
        lines.append(f"**Most promising {label}** — Startup Score = 0.35·Funding + 0.25·News + 0.20·Hiring + "
                     "0.20·Investor quality:")
        for i, s in enumerate(rankings[:10], 1):
            strongest = max(("funding", "news", "hiring", "investor_quality"), key=lambda k: s[k])
            lines.append(f"{i}. **{s['name']}** — score {s['score']:.2f} (funding {s['funding']:.2f}, "
                         f"news {s['news']:.2f}, "
                   f"hiring {s['hiring']:.2f}, investors {s['investor_quality']:.2f}); total funding "
                   f"{format_usd(s.get('total_funding'))}; strongest signal: {strongest.replace('_', ' ')}"
                   f"{_doc_ref(docs, [s['company_id']], 1)}")
    elif intent == "company_overview" and rows:
        for r in rows:
            if "founders" not in r:
                continue
            lines.append(f"**{r['name']}** — {r.get('description') or ''} [G]")
            bullet(f"Sector: {r.get('sector')}; founded {r.get('founded_year')} in {r.get('country')}; "
                   f"~{r.get('employees')} employees (growth {r.get('employee_growth_pct')}%)")
            bullet(f"Total funding: {format_usd(r.get('total_funding'))}; investors: {_names(r.get('investors'), 6)}")
            bullet(f"Founders: {_names(r.get('founders'))}")
            bullet(f"Competitors: {_names(r.get('competitors'), 6)}; partners: {_names(r.get('partners'), 4)}")
            if r.get("acquisitions"):
                bullet(f"Acquisitions: {_names(r['acquisitions'])}")
    elif rows:  # LLM-generated Cypher or other intents: render rows generically
        lines.append("**Knowledge graph results** [G]:")
        for r in rows[:MAX_ITEMS]:
            bullet("; ".join(f"{k}: {_fmt(v)}" for k, v in r.items()))

    if intent in ("competitor_investors", "founder_background") and paths:
        lines.append("Example relationship paths:")
        for p in paths[:5]:
            bullet(p)

    if docs and (not lines or state.get("query_type") in ("vector", "hybrid")):
        had_graph_answer = bool(lines)
        lines.append("**From retrieved documents:**" if had_graph_answer else "**Based on retrieved documents:**")
        for i, d in enumerate(docs[:2 if had_graph_answer else 4], 1):
            content = d["content"]
            snippet = content if len(content) <= 320 else content[:320].rsplit(" ", 1)[0] + "…"
            bullet(f"{snippet} [D{i}]")

    if not lines:
        lines.append("I couldn't find information in the knowledge graph or document store that answers this "
                     "question. Try naming a specific company, investor, founder or sector.")
    for note in notes:
        lines.append(f"\n_Note: {note}_")
    return "\n".join(lines)


def _rel_detail(details: Any) -> str:
    if not isinstance(details, dict):
        return ""
    bits = []
    if details.get("total_amount"):
        bits.append(f"{format_usd(details['total_amount'])} across {details.get('rounds', '?')} round(s)")
    if details.get("lead"):
        bits.append("lead investor")
    if details.get("since"):
        bits.append(f"since {details['since']}")
    if details.get("description"):
        bits.append(details["description"])
    if details.get("date"):
        bits.append(str(details["date"]))
    return f" ({'; '.join(bits)})" if bits else ""


def _fmt(v: Any) -> str:
    if isinstance(v, float) and v > 1e5:
        return format_usd(v)
    if isinstance(v, list):
        return _names(v, 5)
    return str(v)


# ------------------------------------------------------------ LLM context

def build_context(state: dict[str, Any]) -> str:
    parts = [f"Query interpretation: intent={state['intent']}, retrieval={state['query_type']}, "
             f"filters={json.dumps({k: v for k, v in (state.get('entities') or {}).items() if v})}"]
    rows = scalar_rows((state.get("graph") or {}).get("rows") or [])
    if rows:
        parts.append("Knowledge graph results [G]:\n" +
                     "\n".join(json.dumps(r, default=str) for r in rows[:MAX_CONTEXT_ROWS]))
    if state.get("paths"):
        parts.append("Relationship paths [G]:\n" + "\n".join(state["paths"]))
    if state.get("in_common"):
        parts.append(f"Shared between compared companies [G]: {json.dumps(state['in_common'])}")
    if state.get("similar"):
        parts.append("Similar companies (score, components, shared tech/investors):\n" +
                     "\n".join(json.dumps(s, default=str) for s in state["similar"][:10]))
    if state.get("rankings"):
        parts.append("Startup scores (0.35 funding + 0.25 news + 0.20 hiring + 0.20 investor quality):\n" +
                     "\n".join(json.dumps(s, default=str) for s in state["rankings"][:10]))
    for i, d in enumerate(state.get("documents") or [], 1):
        parts.append(f"[D{i}] {d['title']} ({d.get('doc_type')}, {d.get('published_at') or 'undated'}):\n"
                     f"{d['content']}")
    for note in state.get("notes") or []:
        parts.append(f"Note: {note}")
    return "\n\n".join(parts)


# ------------------------------------------------------------ confidence

def compute_confidence(state: dict[str, Any]) -> dict[str, Any]:
    cls_conf = float(state.get("classification_confidence") or 0.5)
    ents = state.get("entities") or {}
    n_entities = sum(len(ents.get(k) or []) for k in ("companies", "investors", "founders", "technologies",
                                                     "employers"))
    entity_score = 1.0 if n_entities or ents.get("topics") else 0.6

    n_rows = len((state.get("graph") or {}).get("rows") or [])
    n_aux = len(state.get("similar") or []) + len(state.get("rankings") or [])
    graph_ev = min(1.0, (n_rows + n_aux) / 3)
    docs = state.get("documents") or []
    top = max((d["score"] for d in docs), default=0.0)
    vector_ev = max(0.0, min(1.0, (top - 0.15) / 0.45)) if docs else 0.0

    qt = state.get("query_type")
    if qt == "graph":
        evidence = graph_ev
    elif qt == "vector":
        evidence = vector_ev
    else:
        evidence = 0.7 * max(graph_ev, vector_ev) + 0.3 * min(graph_ev, vector_ev)
    if state.get("errors"):
        evidence *= 0.8
    score = round(0.3 * cls_conf + 0.2 * entity_score + 0.5 * evidence, 2)
    level = "high" if score >= 0.75 else "medium" if score >= 0.5 else "low"
    return {"score": score, "level": level, "components": {
        "classification": round(cls_conf, 2), "entity_resolution": entity_score,
        "graph_evidence": round(graph_ev, 2), "document_evidence": round(vector_ev, 2)}}


def build_sources(state: dict[str, Any]) -> list[dict[str, Any]]:
    sources: list[dict[str, Any]] = []
    if (state.get("graph") or {}).get("rows") or state.get("similar") or state.get("rankings"):
        sources.append({"id": "G", "type": "knowledge_graph", "title": "Neo4j knowledge graph",
                        "detail": [q["purpose"] for q in state.get("cypher") or []]})
    for i, d in enumerate(state.get("documents") or [], 1):
        sources.append({"id": f"D{i}", "type": d.get("doc_type"), "title": d["title"], "url": d.get("source_url"),
                        "published_at": d.get("published_at"), "score": round(d["score"], 3),
                        "source": d.get("source")})
    return sources
