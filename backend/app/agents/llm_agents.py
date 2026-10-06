"""LLM-backed variants of the agents. Each returns None on failure so callers fall back to rules."""

from __future__ import annotations

import json
import logging
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.agents.classifier import INTENT_DESCRIPTIONS, INTENT_QUERY_TYPE, INTENTS, Classification
from app.agents.cypher import CYPHER_PROMPT
from app.agents.entities import TOPICS, ExtractedEntities
from app.db.neo4j_store import GRAPH_SCHEMA

log = logging.getLogger(__name__)


class ClassificationOut(BaseModel):
    intent: str = Field(description=f"One of: {', '.join(INTENTS)}")
    query_type: Literal["graph", "vector", "hybrid"]
    confidence: float = Field(ge=0, le=1)
    reason: str
    different_investors: bool = Field(
        default=False, description="True if the user wants results funded by different investors"
    )


class EntitiesOut(BaseModel):
    companies: list[str] = Field(default_factory=list, description="Company names that are the subject")
    investors: list[str] = Field(default_factory=list)
    founders: list[str] = Field(default_factory=list)
    technologies: list[str] = Field(default_factory=list)
    employers: list[str] = Field(default_factory=list,
                                 description="Former employers of founders, e.g. 'Google' in 'ex-Google founders'")
    topics: list[str] = Field(default_factory=list, description=f"Sector topics from: {', '.join(TOPICS)}")
    round_types: list[str] = Field(default_factory=list, description="e.g. 'Seed', 'Series A', 'Series B'")
    date_from: str | None = Field(default=None, description="ISO date lower bound, e.g. 2025-01-01")
    date_to: str | None = Field(default=None, description="ISO date upper bound")


async def llm_classify(llm: Any, question: str, ents: ExtractedEntities) -> Classification | None:
    intents = "\n".join(f"- {k} ({INTENT_QUERY_TYPE[k]}): {v}" for k, v in INTENT_DESCRIPTIONS.items())
    prompt = (
        "Classify a startup-intelligence question.\n"
        "query_type: 'graph' for relationship / multi-hop / filtering questions answerable from a knowledge "
        "graph, 'vector' for descriptive or news questions answered from documents, 'hybrid' when both are "
        f"needed.\nIntents:\n{intents}\n\nEntities already detected: {json.dumps(ents.to_dict())}\n\n"
        f"Question: {question}"
    )
    try:
        out: ClassificationOut = await llm.with_structured_output(ClassificationOut).ainvoke(prompt)
    except Exception as exc:
        log.warning("LLM classification failed: %s", exc)
        return None
    if out.intent not in INTENT_QUERY_TYPE:
        return None
    return Classification(out.query_type, out.intent, out.confidence, out.reason, out.different_investors)


async def llm_extract(llm: Any, question: str) -> dict[str, Any] | None:
    prompt = (
        "Extract entities and filters from this startup-intelligence question. Only include names that "
        "appear in or are clearly implied by the question. 'after 2024' means date_from 2025-01-01.\n\n"
        f"Question: {question}"
    )
    try:
        out: EntitiesOut = await llm.with_structured_output(EntitiesOut).ainvoke(prompt)
        return out.model_dump()
    except Exception as exc:
        log.warning("LLM entity extraction failed: %s", exc)
        return None


async def llm_generate_cypher(llm: Any, question: str, ents: ExtractedEntities, limit: int) -> str | None:
    entities = {e["name"]: e["id"] for e in ents.all_entities()}
    filters = {k: v for k, v in ents.to_dict().items()
               if k in ("topics", "round_types", "date_from", "date_to") and v}
    if filters.get("topics"):
        filters["topic_terms (match lowercase against c.sector, c.tags or Technology.name)"] = ents.topic_terms()
    prompt = CYPHER_PROMPT.format(schema=GRAPH_SCHEMA, entities=json.dumps(entities),
                                  filters=json.dumps(filters), question=question, limit=limit)
    try:
        msg = await llm.ainvoke(prompt)
        return str(msg.content).strip()
    except Exception as exc:
        log.warning("LLM Cypher generation failed: %s", exc)
        return None


ANSWER_SYSTEM = """You are StartupGraph AI, an analyst answering questions about startups, investors,
founders and funding using ONLY the provided context from a knowledge graph and retrieved documents.

Rules:
- Be specific and concise; use bullet points or a short table for lists.
- Cite documents inline as [D1], [D2]... and graph facts as [G].
- When relationship paths are given, explain the key connections (e.g. A -[INVESTED_BY]-> B).
- If startup scores are provided, mention the score and its strongest components.
- If the context does not contain the answer, say so plainly. Never invent facts, amounts or dates.
- Note any assumption about the question (e.g. how a date filter was interpreted)."""


async def llm_answer(llm: Any, question: str, context: str) -> str | None:
    try:
        msg = await llm.ainvoke([("system", ANSWER_SYSTEM),
                                 ("human", f"Context:\n{context}\n\nQuestion: {question}")])
        content = msg.content
        if isinstance(content, list):  # some providers return content blocks
            content = "".join(b.get("text", "") if isinstance(b, dict) else str(b) for b in content)
        return str(content).strip()
    except Exception as exc:
        log.warning("LLM answer generation failed: %s", exc)
        return None
