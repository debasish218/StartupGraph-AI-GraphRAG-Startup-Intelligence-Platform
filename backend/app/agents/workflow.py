"""LangGraph multi-agent workflow.

    route (Agent 1: classification)
      -> extract_entities (Agent 2)
      -> graph_retrieval (Agent 3) and/or vector_retrieval (Agent 4)   [parallel for hybrid]
      -> rank (Agent 5)
      -> answer (Agent 6)
"""

from __future__ import annotations

import asyncio
import logging
import operator
import re
import time
from typing import TYPE_CHECKING, Annotated, Any, TypedDict

from langgraph.graph import END, START, StateGraph

from app.agents import answer as answer_mod
from app.agents.classifier import INTENT_QUERY_TYPE, classify_rules
from app.agents.cypher import CypherQuery, build_queries, neighborhood_query, topic_filter, validate_cypher
from app.agents.entities import ExtractedEntities, extract_entities_rules, merge_llm_entities
from app.agents.llm_agents import llm_answer, llm_classify, llm_extract, llm_generate_cypher
from app.db.neo4j_store import GraphResult

if TYPE_CHECKING:
    from app.container import Container

log = logging.getLogger(__name__)

# Intents that need at least one resolved entity of a given kind.
REQUIRED_ENTITIES = {
    "competitors": ("companies",), "competitor_investors": ("companies",), "investors_of": ("companies",),
    "investor_portfolio": ("investors",), "founder_background": ("employers",),
    "founders_of": ("companies", "founders"), "technology_users": ("technologies",),
    "similar_companies": ("companies",), "compare": ("companies", "investors"),
    "relationship": ("companies", "investors", "founders"),
}
RANKED_INTENTS = {"recommendation", "competitors", "founder_background", "funding_search", "technology_users",
                  "investor_portfolio", "compare"}
FUNDING_DOC_INTENTS = {"funding_search", "investors_of", "active_investors", "investor_portfolio",
                       "competitor_investors"}


class AgentState(TypedDict, total=False):
    question: str
    query_type: str
    intent: str
    classification_confidence: float
    classification_reason: str
    different_investors: bool
    entities: dict[str, Any]
    graph: dict[str, Any]            # {"rows": [...], "nodes": {id: node}, "edges": {id: edge}}
    cypher: list[dict[str, Any]]
    paths: list[str]
    documents: list[dict[str, Any]]
    rankings: list[dict[str, Any]]
    similar: list[dict[str, Any]]
    in_common: dict[str, Any]
    answer: str
    confidence: dict[str, Any]
    sources: list[dict[str, Any]]
    answer_mode: str
    notes: Annotated[list[str], operator.add]
    errors: Annotated[list[str], operator.add]
    trace: Annotated[list[dict[str, Any]], operator.add]


def _trace(agent: str, started: float, **detail: Any) -> list[dict[str, Any]]:
    return [{"agent": agent, "ms": round((time.perf_counter() - started) * 1000, 1), **detail}]


def _entities_obj(d: dict[str, Any]) -> ExtractedEntities:
    return ExtractedEntities(**d)


def build_workflow(c: Container):
    llm = c.llm
    settings = c.settings

    # ---------------------------------------------------------- Agent 1
    async def route(state: AgentState) -> dict[str, Any]:
        t0 = time.perf_counter()
        q = state["question"]
        prescan = extract_entities_rules(q, c.catalog)
        cls = classify_rules(q, prescan)
        mode = "rules"
        if llm is not None and (out := await llm_classify(llm, q, prescan)):
            cls, mode = out, "llm"
        return {
            "query_type": cls.query_type, "intent": cls.intent, "classification_confidence": cls.confidence,
            "classification_reason": cls.reason, "different_investors": cls.different_investors,
            "entities": prescan.to_dict(),
            "trace": _trace("query_classification", t0, mode=mode, intent=cls.intent, query_type=cls.query_type,
                            reason=cls.reason),
        }

    # ---------------------------------------------------------- Agent 2
    async def extract_entities(state: AgentState) -> dict[str, Any]:
        t0 = time.perf_counter()
        ents = _entities_obj(state["entities"])
        mode = "gazetteer"
        if llm is not None and (proposed := await llm_extract(llm, state["question"])):
            ents = merge_llm_entities(ents, proposed, c.catalog)
            mode = "gazetteer+llm"
        update: dict[str, Any] = {"entities": ents.to_dict()}
        notes: list[str] = []
        intent = state["intent"]
        required = REQUIRED_ENTITIES.get(intent)
        if required and not any(getattr(ents, k) for k in required):
            unknown = [m for m in re.findall(r"\b[A-Z][\w.&-]*(?:\s+[A-Z][\w.&-]*)*", state["question"])
                       if m.split()[0] not in {"Who", "What", "Which", "Show", "Find", "How", "The", "Compare"}]
            named = f" ({', '.join(unknown)})" if unknown else ""
            notes.append(f"No matching {' or '.join(required)}{named} were found in the knowledge graph, so the "
                         "question was answered with semantic document search instead.")
            update |= {"intent": "general", "query_type": "vector"}
        update["notes"] = notes
        update["trace"] = _trace("entity_extraction", t0, mode=mode, entities=[
            f"{e['type']}:{e['name']}" for e in ents.all_entities()], topics=ents.topics,
            filters={k: v for k, v in (("round_types", ents.round_types), ("date_from", ents.date_from),
                                       ("date_to", ents.date_to)) if v})
        return update

    def choose_retrieval(state: AgentState) -> list[str]:
        qt = state["query_type"]
        if qt == "graph":
            return ["graph_retrieval"]
        if qt == "vector":
            return ["vector_retrieval"]
        return ["graph_retrieval", "vector_retrieval"]

    # ---------------------------------------------------------- Agent 3
    async def run_queries(queries: list[CypherQuery]) -> tuple[GraphResult, list[dict[str, Any]], list[str]]:
        result, executed, errors = GraphResult(), [], []
        for q in queries:
            try:
                r = await c.graph.read(q.cypher, q.params, timeout=settings.cypher_timeout_s)
                result.merge(r)
                executed.append({"purpose": q.purpose, "cypher": " ".join(q.cypher.split()),
                                 "params": q.params, "rows": len(r.rows), "generated_by": q.generated_by})
            except Exception as exc:  # noqa: BLE001 - surfaced in the trace
                log.warning("Cypher failed (%s): %s", q.purpose, exc)
                errors.append(f"graph query '{q.purpose}' failed: {exc}")
        return result, executed, errors

    async def llm_cypher(question: str, ents: ExtractedEntities) -> list[CypherQuery]:
        if llm is None:
            return []
        raw = await llm_generate_cypher(llm, question, ents, settings.graph_result_limit)
        if not raw:
            return []
        try:
            return [CypherQuery("LLM-generated query", validate_cypher(raw, settings.graph_result_limit),
                                generated_by="llm")]
        except ValueError as exc:
            log.warning("Rejected LLM Cypher: %s", exc)
            return []

    async def graph_retrieval(state: AgentState) -> dict[str, Any]:
        t0 = time.perf_counter()
        intent = state["intent"]
        ents = _entities_obj(state["entities"])
        limit = settings.graph_result_limit
        notes: list[str] = []
        update: dict[str, Any] = {}

        queries = build_queries(intent, ents, limit, state.get("different_investors", False))
        if not queries:
            queries = await llm_cypher(state["question"], ents)
        result, executed, errors = await run_queries(queries)

        # "after 2024" is read strictly (2025+); if nothing matches, relax to include that year.
        if intent == "funding_search" and not result.rows and ents.date_strict and ents.date_from:
            year = int(ents.date_from[:4]) - 1
            ents.date_from, ents.date_strict = f"{year}-01-01", False
            relaxed, ex2, err2 = await run_queries(build_queries(intent, ents, limit))
            if relaxed.rows:
                notes.append(f"No rounds matched strictly after {year}; showing rounds from {year} onward.")
                result, executed, errors = relaxed, executed + ex2, errors + err2
                update["entities"] = ents.to_dict()

        if not result.rows and intent != "similar_companies" and executed and executed[0]["generated_by"] == "template":
            fallback = await llm_cypher(state["question"], ents)
            if fallback:
                r2, ex3, err3 = await run_queries(fallback)
                result.merge(r2)
                executed += ex3
                errors += err3

        if intent == "active_investors" and result.rows:
            names = [r["investor"] for r in result.rows[:8]]
            viz, ex6, _ = await run_queries([CypherQuery("visualise investor portfolios", f"""
                MATCH (c:Company)-[r:INVESTED_BY]->(i:Investor)
                WHERE i.name IN $names AND c.is_startup AND {topic_filter('c')}
                RETURN c, r, i""", {"names": names, "terms": ents.topic_terms()})])
            result.nodes.update(viz.nodes)
            result.edges.update(viz.edges)
            executed += ex6

        if intent == "similar_companies" and ents.companies:
            target = ents.companies[0]["id"]
            similar = await c.similarity.similar(target, limit=10,
                                                 different_investors=state.get("different_investors", False))
            update["similar"] = similar
            viz, ex4, _ = await run_queries([neighborhood_query(
                [target] + [s["id"] for s in similar[:6]], per_node=8,
                rel_types=["INVESTED_BY", "USES_TECH", "COMPETES_WITH"])])
            result.merge(viz)
            executed += ex4

        if intent == "compare":
            ids = [e["id"] for e in ents.companies or ents.investors]
            update["in_common"] = (await c.analytics.compare(ids))["in_common"]
            rel, ex5, _ = await run_queries(build_queries("relationship", ents, limit)[:1])
            result.merge(rel)
            executed += ex5

        paths = answer_mod.extract_paths(result.rows)
        update |= {
            "graph": {"rows": result.rows, "nodes": result.nodes, "edges": result.edges},
            "cypher": executed, "paths": paths, "notes": notes, "errors": errors,
            "trace": _trace("graph_retrieval", t0, queries=[q["purpose"] for q in executed],
                            rows=len(result.rows), nodes=len(result.nodes), edges=len(result.edges)),
        }
        return update

    # ---------------------------------------------------------- Agent 4
    async def vector_retrieval(state: AgentState) -> dict[str, Any]:
        t0 = time.perf_counter()
        ents = _entities_obj(state["entities"])
        k = settings.vector_top_k
        doc_types = ["news", "funding_report", "market_report"] if state["intent"] in FUNDING_DOC_INTENTS else None
        try:
            q_emb = await asyncio.to_thread(c.embedder.embed_query, state["question"])
            entity_ids = [e["id"] for e in ents.companies + ents.investors]
            hits: list[dict[str, Any]] = []
            if entity_ids:
                hits = await c.vectors.search(q_emb, k=k, doc_types=doc_types, company_ids=entity_ids)
            general = await c.vectors.search(q_emb, k=k, doc_types=doc_types)
            # Documents about the named entities come first; general hits fill the remaining slots.
            seen = {h["document_id"] for h in hits}
            head = max(k // 2, 3)
            hits = (hits[:head] + [h for h in general if h["document_id"] not in seen] + hits[head:])[:k]
            errors: list[str] = []
        except Exception as exc:  # noqa: BLE001
            log.warning("Vector retrieval failed: %s", exc)
            hits, errors = [], [f"vector search failed: {exc}"]
        return {"documents": hits, "errors": errors,
                "trace": _trace("vector_retrieval", t0, documents=len(hits),
                                top_score=round(hits[0]["score"], 3) if hits else None)}

    # ---------------------------------------------------------- Agent 5
    async def rank(state: AgentState) -> dict[str, Any]:
        t0 = time.perf_counter()
        intent = state["intent"]
        graph = state.get("graph") or {"rows": [], "nodes": {}, "edges": {}}
        if intent not in RANKED_INTENTS:
            return {"trace": _trace("ranking", t0, skipped=f"not needed for intent '{intent}'")}
        subject_ids = {e["id"] for e in (state["entities"].get("companies") or [])}
        if intent == "compare":
            candidates = list(subject_ids)
        else:
            candidates = [n["id"] for n in graph["nodes"].values()
                          if "Company" in n.get("labels", []) and n.get("is_startup") and n["id"] not in subject_ids]
        if not candidates:
            return {"trace": _trace("ranking", t0, skipped="no candidate startups")}
        scores = [s.to_dict() for s in await c.ranking.score_companies(candidates)]
        update: dict[str, Any] = {"rankings": scores}
        if intent == "recommendation" and scores:
            viz = await c.graph.read(**_neighborhood_kwargs([s["company_id"] for s in scores[:6]]))
            graph = {"rows": graph["rows"], "nodes": {**graph["nodes"], **viz.nodes},
                     "edges": {**graph["edges"], **viz.edges}}
            update["graph"] = graph
        update["trace"] = _trace("ranking", t0, ranked=len(scores),
                                 top=[f"{s['name']} ({s['score']:.2f})" for s in scores[:3]])
        return update

    # ---------------------------------------------------------- Agent 6
    async def answer(state: AgentState) -> dict[str, Any]:
        t0 = time.perf_counter()
        text, mode = None, "template"
        if llm is not None:
            text = await llm_answer(llm, state["question"], answer_mod.build_context(dict(state)))
            mode = "llm" if text else "template"
        if not text:
            text = answer_mod.compose_answer(dict(state))
        return {
            "answer": text, "answer_mode": mode,
            "confidence": answer_mod.compute_confidence(dict(state)),
            "sources": answer_mod.build_sources(dict(state)),
            "trace": _trace("answer_generation", t0, mode=mode),
        }

    g = StateGraph(AgentState)
    g.add_node("route", route)
    g.add_node("extract_entities", extract_entities)
    g.add_node("graph_retrieval", graph_retrieval)
    g.add_node("vector_retrieval", vector_retrieval)
    g.add_node("rank", rank)
    g.add_node("answer", answer)
    g.add_edge(START, "route")
    g.add_edge("route", "extract_entities")
    g.add_conditional_edges("extract_entities", choose_retrieval, ["graph_retrieval", "vector_retrieval"])
    g.add_edge("graph_retrieval", "rank")
    g.add_edge("vector_retrieval", "rank")
    g.add_edge("rank", "answer")
    g.add_edge("answer", END)
    return g.compile()


def _neighborhood_kwargs(ids: list[str]) -> dict[str, Any]:
    q = neighborhood_query(ids, per_node=6, rel_types=["INVESTED_BY", "USES_TECH", "FOUNDED_BY"])
    return {"cypher": q.cypher, "params": q.params}


def initial_state(question: str) -> AgentState:
    return {"question": question, "notes": [], "errors": [], "trace": []}


__all__ = ["build_workflow", "initial_state", "AgentState", "INTENT_QUERY_TYPE"]
