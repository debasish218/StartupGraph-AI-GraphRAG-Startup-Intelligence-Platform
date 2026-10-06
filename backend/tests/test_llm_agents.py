"""LLM agent wiring, tested with a stub chat model (no API calls)."""

from types import SimpleNamespace

from app.agents.cypher import UnsafeCypherError, validate_cypher
from app.agents.entities import extract_entities_rules, merge_llm_entities
from app.agents.llm_agents import (
    ClassificationOut,
    EntitiesOut,
    llm_answer,
    llm_classify,
    llm_extract,
    llm_generate_cypher,
)
from app.ingestion.events import EventOut, EventsOut, extract_events


class StubLLM:
    """Mimics the LangChain chat-model surface the agents use."""

    def __init__(self, structured=None, text="", fail=False):
        self.structured, self.text, self.fail = structured or {}, text, fail
        self.prompts = []

    def with_structured_output(self, schema):
        async def ainvoke(prompt):
            self.prompts.append(prompt)
            if self.fail:
                raise RuntimeError("provider down")
            return self.structured[schema]
        return SimpleNamespace(ainvoke=ainvoke)

    async def ainvoke(self, prompt):
        self.prompts.append(prompt)
        if self.fail:
            raise RuntimeError("provider down")
        return SimpleNamespace(content=self.text)


async def test_llm_classify_validates_intent(catalog):
    ents = extract_entities_rules("Who funds OpenAI competitors?", catalog)
    good = StubLLM({ClassificationOut: ClassificationOut(intent="competitor_investors", query_type="graph",
                                                         confidence=0.95, reason="multi-hop")})
    cls = await llm_classify(good, "Who funds OpenAI competitors?", ents)
    assert cls.intent == "competitor_investors" and cls.confidence == 0.95
    bogus = StubLLM({ClassificationOut: ClassificationOut(intent="make_coffee", query_type="graph",
                                                          confidence=1, reason="?")})
    assert await llm_classify(bogus, "q", ents) is None
    assert await llm_classify(StubLLM(fail=True), "q", ents) is None


async def test_llm_extraction_is_grounded_in_catalog(catalog):
    llm = StubLLM({EntitiesOut: EntitiesOut(companies=["OpenAI", "Hallucinated Labs"], employers=["Google"],
                                            topics=["Computer Vision", "Not A Topic"], round_types=["Series B"])})
    proposed = await llm_extract(llm, "q")
    ents = merge_llm_entities(extract_entities_rules("q", catalog), proposed, catalog)
    assert [c["id"] for c in ents.companies] == ["openai"]
    assert [e["id"] for e in ents.employers] == ["google"]
    assert ents.topics == ["Computer Vision"] and ents.round_types == ["Series B"]


async def test_llm_cypher_must_pass_validation(catalog):
    ents = extract_entities_rules("Who invested in OpenAI?", catalog)
    llm = StubLLM(text="```cypher\nMATCH (c:Company {id: 'openai'})-[:INVESTED_BY]->(i) RETURN i.name\n```")
    raw = await llm_generate_cypher(llm, "Who invested in OpenAI?", ents, 25)
    assert validate_cypher(raw, 25).endswith("LIMIT 25")
    assert "openai" in llm.prompts[0] and "INVESTED_BY" in llm.prompts[0]  # ids + schema in prompt
    evil = StubLLM(text="MATCH (n) DETACH DELETE n")
    try:
        validate_cypher(await llm_generate_cypher(evil, "q", ents, 25))
        raise AssertionError("unsafe Cypher accepted")
    except UnsafeCypherError:
        pass


async def test_llm_answer_handles_content_blocks_and_failure():
    llm = StubLLM()
    llm.text = [{"type": "text", "text": "Anthropic competes with OpenAI [G]."}]
    assert await llm_answer(llm, "q", "ctx") == "Anthropic competes with OpenAI [G]."
    assert await llm_answer(StubLLM(fail=True), "q", "ctx") is None


async def test_event_extraction_falls_back_to_regex():
    llm = StubLLM({EventsOut: EventsOut(events=[EventOut(type="acquisition", company="Nvidia",
                                                         counterparty="Run:ai", amount_usd=7e8)])})
    [ev] = await extract_events("Nvidia buys Run:ai", "", llm)
    assert (ev.type, ev.counterparty, ev.amount) == ("acquisition", "Run:ai", 7e8)
    [ev2] = await extract_events("Nvidia acquires Run:ai for $700 million", "", StubLLM(fail=True))
    assert ev2.type == "acquisition" and ev2.amount == 7e8
