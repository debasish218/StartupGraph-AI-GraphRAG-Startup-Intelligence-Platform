from __future__ import annotations

from datetime import date
from typing import Any

from pydantic import BaseModel, Field


class QueryRequest(BaseModel):
    question: str = Field(min_length=3, max_length=500, examples=["Who funds OpenAI competitors?"])


class GraphNode(BaseModel):
    id: str
    label: str
    type: str
    labels: list[str]
    properties: dict[str, Any]


class GraphEdge(BaseModel):
    id: str
    source: str
    target: str
    type: str
    properties: dict[str, Any] = {}


class GraphPayload(BaseModel):
    nodes: list[GraphNode] = []
    edges: list[GraphEdge] = []


class Confidence(BaseModel):
    score: float
    level: str
    components: dict[str, float]


class QueryResponse(BaseModel):
    question: str
    answer: str
    answer_mode: str
    query_type: str
    intent: str
    classification_reason: str
    entities: dict[str, Any]
    confidence: Confidence
    sources: list[dict[str, Any]]
    paths: list[str]
    cypher: list[dict[str, Any]]
    graph: GraphPayload
    documents: list[dict[str, Any]]
    rankings: list[dict[str, Any]]
    similar: list[dict[str, Any]]
    notes: list[str]
    errors: list[str]
    trace: list[dict[str, Any]]
    latency_ms: float


class ArticleIn(BaseModel):
    title: str = Field(min_length=5, max_length=500)
    body: str = Field(default="", max_length=20000)
    url: str | None = None
    published_at: date | None = None


class RSSIngestIn(BaseModel):
    feeds: list[str] | None = None
    max_items: int = Field(default=30, ge=1, le=200)


class YCIngestIn(BaseModel):
    industry: str | None = Field(default=None, examples=["B2B"])
    tag: str | None = Field(default=None, examples=["Computer Vision"])
    batch: str | None = Field(default=None, examples=["Summer 2024"])
    limit: int = Field(default=100, ge=1, le=2000)


# Node types in priority order for the visual "type" of multi-label nodes.
NODE_TYPE_PRIORITY = ["Founder", "Technology", "FundingRound", "NewsArticle", "Company", "Investor"]


def node_type(labels: list[str], props: dict[str, Any]) -> str:
    if "Company" in labels and "Investor" in labels:
        return "Company"
    for t in NODE_TYPE_PRIORITY:
        if t in labels:
            return t
    return labels[0] if labels else "Entity"


def graph_payload(nodes: dict[str, dict[str, Any]], edges: dict[str, dict[str, Any]]) -> GraphPayload:
    out_nodes = []
    for nid, n in nodes.items():
        labels = n.get("labels", [])
        props = {k: v for k, v in n.items() if k not in ("labels", "id")}
        out_nodes.append(GraphNode(id=nid, label=str(n.get("name") or nid), type=node_type(labels, props),
                                   labels=labels, properties=props))
    out_edges = [GraphEdge(id=e["id"], source=e["source"], target=e["target"], type=e["type"],
                           properties={k: v for k, v in e.items() if k not in ("id", "source", "target", "type")})
                 for e in edges.values() if e["source"] in nodes and e["target"] in nodes]
    return GraphPayload(nodes=out_nodes, edges=out_edges)
