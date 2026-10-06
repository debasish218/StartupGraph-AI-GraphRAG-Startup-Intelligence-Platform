"""Query classification (Agent 1): decides graph / vector / hybrid retrieval and the intent."""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.agents.entities import ExtractedEntities

# intent -> retrieval strategy
INTENT_QUERY_TYPE: dict[str, str] = {
    "competitors": "graph",
    "competitor_investors": "graph",
    "investors_of": "graph",
    "active_investors": "graph",
    "investor_portfolio": "graph",
    "founder_background": "graph",
    "founders_of": "graph",
    "funding_search": "graph",
    "acquisitions": "graph",
    "technology_users": "graph",
    "relationship": "graph",
    "similar_companies": "hybrid",
    "compare": "hybrid",
    "recommendation": "hybrid",
    "company_overview": "hybrid",
    "general": "vector",
}

INTENTS = list(INTENT_QUERY_TYPE)

INTENT_DESCRIPTIONS = {
    "competitors": "companies competing with a given company",
    "competitor_investors": "investors that fund the competitors of a given company",
    "investors_of": "investors in a given company",
    "active_investors": "investors most active in a sector/technology",
    "investor_portfolio": "companies a given investor has backed",
    "founder_background": "startups whose founders previously worked at a given employer",
    "founders_of": "founders of a company, or companies founded by a person",
    "funding_search": "funding rounds filtered by round type, date and sector",
    "acquisitions": "acquisitions made by or of companies",
    "technology_users": "companies using a technology",
    "relationship": "how several entities are connected in the graph",
    "similar_companies": "companies similar to a given company",
    "compare": "side-by-side comparison of companies",
    "recommendation": "ranking promising startups in a sector",
    "company_overview": "structured overview of one company (graph + documents)",
    "general": "descriptive / news questions answered from documents",
}


@dataclass
class Classification:
    query_type: str
    intent: str
    confidence: float
    reason: str
    different_investors: bool = False


def _has(pattern: str, text: str) -> bool:
    return re.search(pattern, text, re.I) is not None


INVESTOR_WORDS = (r"\b(investors?|vcs?|venture|backers?|funds?|funded|funders?|funding|financ\w*|backs|backed|"
                  r"invest\w*)\b")
COMPETE_WORDS = r"\b(compet\w*|rivals?|alternatives? to|contenders?|challengers?)\b"
DESCRIPTIVE = r"^\s*(what|who)\s+(is|are|was)\b|\b(tell me about|describe|explain|summar\w+|overview of|what does)\b"
NEWS_WORDS = r"\b(news|latest|recent(ly)?|announce\w*|headlines?|happened|update)\b"


def classify_rules(question: str, ents: ExtractedEntities) -> Classification:
    q = question.strip()
    n_companies = len(ents.companies)
    n_named = len(ents.companies) + len(ents.investors) + len(ents.founders)
    has_topic = bool(ents.topics or ents.technologies)

    def result(intent: str, confidence: float, reason: str, **kw) -> Classification:
        return Classification(INTENT_QUERY_TYPE[intent], intent, confidence, reason, **kw)

    if _has(r"\bsimilar\b|\blike\s+[A-Z]|\bcomparable to\b|\blook[- ]?alikes?\b", q) and n_companies:
        diff = _has(r"different investors|other investors|not (?:funded|backed) by|without .*investors|"
                    r"different backers|no shared investors", q)
        return result("similar_companies", 0.9, "asks for companies similar to a named company",
                      different_investors=diff)
    if _has(r"\bcompare\b|\bcomparison\b|\bvs\.?\b|\bversus\b|difference between", q) and n_named >= 2:
        return result("compare", 0.9, "compares two or more named entities")
    if _has(r"relationship|connect\w*|related|link(?:ed|s)? between|ties between|how .* relate", q) and n_named >= 2:
        return result("relationship", 0.9, "asks how several entities are connected")
    if ents.employers and _has(r"found\w*|startups?|companies|started|built|launched|co-?found", q):
        return result("founder_background", 0.9, "filters startups by founders' former employers")
    if _has(COMPETE_WORDS, q) and not n_companies and has_topic:
        return result("recommendation", 0.75, "asks which startups compete in a sector; ranking that sector")
    # Relational intents are kept even when the company is unknown, so the entity agent can explain the
    # fallback instead of silently answering a different question.
    if _has(COMPETE_WORDS, q) and _has(INVESTOR_WORDS, q):
        return result("competitor_investors", 0.9 if n_companies else 0.5,
                      "multi-hop: company -> competitors -> investors")
    if _has(COMPETE_WORDS, q):
        return result("competitors", 0.9 if n_companies else 0.5, "asks for competitors of a company")
    if _has(r"\bacqui\w+|\bbought\b|\bbuy(?:s|ing)?\b|\bpurchas\w+|\bm&a\b", q):
        return result("acquisitions", 0.85, "asks about acquisitions")
    if ents.round_types or ents.date_from or ents.date_to or (
        _has(r"\braised?\b|\braising\b|funding rounds?", q) and has_topic and not n_named
    ):
        return result("funding_search", 0.85, "filters funding rounds by type/date/sector")
    if _has(INVESTOR_WORDS, q) and _has(r"\bwho\b|\bwhich\b|\blist\b|\bshow\b|\bactive\w*|\btop\b|\bmost\b", q):
        if n_companies and not ents.investors:
            return result("investors_of", 0.9, "asks who invested in a named company")
        if ents.investors and _has(r"portfolio|invested in|backed|back|fund(?:ed|s)?\b|bet", q) and not n_companies:
            return result("investor_portfolio", 0.85, "asks what a named investor has backed")
        if has_topic or not n_named:
            return result("active_investors", 0.85, "asks which investors are active in a sector")
    if ents.investors and not n_companies and _has(r"portfolio|invest|back|fund", q):
        return result("investor_portfolio", 0.8, "asks what a named investor has backed")
    if _has(r"\bfounders?\b|\bfounded by\b|\bwho (?:founded|started|created)\b|\bco-?founders?\b", q) and (
        n_companies or ents.founders
    ):
        return result("founders_of", 0.85, "asks about founders")
    if ents.founders and _has(r"\bfound\w*|\bstart\w*|\bcompan\w+", q):
        return result("founders_of", 0.8, "asks what a person founded")
    if _has(r"promising|\btop\b|\bbest\b|recommend\w*|\brank\w*|hottest|fastest[- ]growing|leading|"
            r"high[- ]potential", q):
        return result("recommendation", 0.85, "asks to rank/recommend startups")
    if ents.technologies and _has(r"\buse[sd]?\b|\busing\b|built on|\bbuild\w*\b|adopt\w*|leverag\w*", q):
        return result("technology_users", 0.8, "asks which companies use a technology")
    if n_named >= 3:
        return result("relationship", 0.7, "several entities named; showing their connections")
    if _has(NEWS_WORDS, q) or _has(DESCRIPTIVE, q):
        return result("general", 0.8, "descriptive or news question; semantic retrieval fits best")
    if n_named == 1:
        return result("company_overview", 0.6, "single entity without a specific relation; graph + documents")
    if has_topic:
        return result("recommendation", 0.55, "sector mentioned without specific relation; ranking startups")
    return result("general", 0.5, "no graph intent detected; using semantic search")
