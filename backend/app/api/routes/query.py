import time

from fastapi import APIRouter, Depends

from app.agents.workflow import initial_state
from app.api.deps import get_container
from app.api.schemas import QueryRequest, QueryResponse, graph_payload
from app.container import Container

router = APIRouter(prefix="/api", tags=["query"])


@router.post("/query", response_model=QueryResponse)
async def query(req: QueryRequest, c: Container = Depends(get_container)) -> QueryResponse:
    """Answer a question with the multi-agent GraphRAG workflow."""
    t0 = time.perf_counter()
    state = await c.workflow.ainvoke(initial_state(req.question.strip()))
    graph = state.get("graph") or {"nodes": {}, "edges": {}}
    documents = [{
        "title": d["title"], "doc_type": d["doc_type"], "snippet": d["content"][:400], "score": round(d["score"], 3),
        "url": d.get("source_url"), "published_at": d.get("published_at"), "source": d.get("source"),
        "company_ids": d.get("company_ids") or [],
    } for d in state.get("documents") or []]
    return QueryResponse(
        question=req.question, answer=state["answer"], answer_mode=state.get("answer_mode", "template"),
        query_type=state["query_type"], intent=state["intent"],
        classification_reason=state.get("classification_reason", ""), entities=state.get("entities") or {},
        confidence=state["confidence"], sources=state.get("sources") or [], paths=state.get("paths") or [],
        cypher=state.get("cypher") or [], graph=graph_payload(graph["nodes"], graph["edges"]),
        documents=documents, rankings=state.get("rankings") or [], similar=state.get("similar") or [],
        notes=state.get("notes") or [], errors=state.get("errors") or [], trace=state.get("trace") or [],
        latency_ms=round((time.perf_counter() - t0) * 1000, 1),
    )
