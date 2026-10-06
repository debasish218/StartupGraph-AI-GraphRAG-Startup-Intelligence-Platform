"""Cypher generation for the Graph Retrieval Agent (Agent 3).

Known intents map to parameterised, reviewed templates (no string interpolation of
user input). For anything else an LLM can generate Cypher, which must pass
``validate_cypher`` and runs in a READ transaction.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from app.agents.entities import ExtractedEntities


@dataclass
class CypherQuery:
    purpose: str
    cypher: str
    params: dict[str, Any] = field(default_factory=dict)
    generated_by: str = "template"


def topic_filter(var: str) -> str:
    """Cypher predicate: company `var` matches any of $terms by sector, tag or technology."""
    return (
        f"(size($terms) = 0 OR any(term IN $terms WHERE toLower({var}.sector) = term "
        f"OR any(tag IN coalesce({var}.tags, []) WHERE toLower(tag) = term) "
        f"OR EXISTS {{ ({var})-[:USES_TECH]->(tt:Technology) WHERE toLower(tt.name) = term }}))"
    )


NOT_ACQUIRED = "NOT EXISTS { (:Company)-[:ACQUIRED]->(c) }"

COMPANY_SUMMARY = """
MATCH (c:Entity) WHERE c.id IN $ids
RETURN c.id AS id, c.name AS name, c.description AS description, c.sector AS sector, c.country AS country,
       c.founded_year AS founded_year, c.employee_count AS employees, c.employee_growth_pct AS employee_growth_pct,
       c.total_funding AS total_funding, c.website AS website,
       [(c)-[:FOUNDED_BY]->(f) | f.name] AS founders,
       [(c)-[r:INVESTED_BY]->(i) | i.name] AS investors,
       [(c)-[r:INVESTED_BY]->(i) WHERE r.lead | i.name] AS lead_investors,
       [(c)-[:USES_TECH]->(t) | t.name] AS technologies,
       [(c)-[:COMPETES_WITH]-(x) | x.name] AS competitors,
       [(c)-[:PARTNERS_WITH]-(x) | x.name] AS partners,
       [(c)-[:ACQUIRED]->(x) | x.name] AS acquisitions,
       [(x)-[:ACQUIRED]->(c) | x.name] AS acquired_by,
       [(c)-[:RAISED]->(r) | {round: r.round_type, amount: r.amount, date: toString(r.date)}] AS funding_rounds
"""

NEIGHBORHOOD = """
MATCH (c:Entity) WHERE c.id IN $ids
OPTIONAL MATCH (c)-[r]-(n:Entity)
WHERE NOT n:NewsArticle AND NOT n:FundingRound AND type(r) IN $rel_types
WITH c, type(r) AS rel_type, r, n ORDER BY coalesce(n.total_funding, 0) DESC, coalesce(n.quality, 0) DESC
WITH c, rel_type, collect(r)[..$per_node] AS rels, collect(n)[..$per_node] AS neighbors
RETURN c AS center, rels, neighbors
"""

DEFAULT_REL_TYPES = ["FOUNDED_BY", "INVESTED_BY", "USES_TECH", "COMPETES_WITH", "PARTNERS_WITH", "ACQUIRED",
                     "WORKED_AT"]


def neighborhood_query(ids: list[str], per_node: int = 25, rel_types: list[str] | None = None) -> CypherQuery:
    """Neighbours of `ids`, keeping at most `per_node` per relationship type so every role is shown."""
    return CypherQuery("neighborhood", NEIGHBORHOOD,
                       {"ids": ids, "per_node": per_node, "rel_types": rel_types or DEFAULT_REL_TYPES})


def ids(group: list[dict[str, str]]) -> list[str]:
    return [e["id"] for e in group]


def build_queries(intent: str, ents: ExtractedEntities, limit: int, different_investors: bool = False
                  ) -> list[CypherQuery]:
    """Return the template queries for an intent (empty if the intent needs entities that are missing)."""
    terms = ents.topic_terms()
    companies = ids(ents.companies)
    investors = ids(ents.investors)
    lim = ents.limit or limit

    if intent == "competitors" and companies:
        return [CypherQuery("competitors", """
            MATCH (c:Company)-[r:COMPETES_WITH]-(x:Company) WHERE c.id IN $ids
            RETURN c.name AS company, x.name AS competitor, x.sector AS sector, x.total_funding AS total_funding,
                   [(x)-[:INVESTED_BY]->(i) | i.name][..5] AS investors, c AS c, r AS r, x AS x
            ORDER BY coalesce(x.total_funding, 0) DESC LIMIT $limit""", {"ids": companies, "limit": lim})]

    if intent == "competitor_investors" and companies:
        return [CypherQuery("investors of competitors (multi-hop)", """
            MATCH p = (c:Company)-[:COMPETES_WITH]-(x:Company)-[:INVESTED_BY]->(i:Investor)
            WHERE c.id IN $ids AND NOT i.id IN $ids
            WITH i, collect(DISTINCT x.name) AS competitors_funded, collect(p)[..3] AS paths
            RETURN i.name AS investor, i.type AS investor_type, competitors_funded,
                   size(competitors_funded) AS competitors_count, paths
            ORDER BY competitors_count DESC, i.quality DESC LIMIT $limit""", {"ids": companies, "limit": lim})]

    if intent == "investors_of" and companies:
        return [CypherQuery("investors of company", """
            MATCH (c:Company)-[r:INVESTED_BY]->(i:Investor) WHERE c.id IN $ids
            RETURN c.name AS company, i.name AS investor, i.type AS investor_type, r.lead AS lead,
                   r.rounds AS rounds, r.total_amount AS round_amounts, toString(r.last_round_date) AS last_round,
                   c AS c, r AS r, i AS i
            ORDER BY r.lead DESC, r.total_amount DESC LIMIT $limit""", {"ids": companies, "limit": lim})]

    if intent == "active_investors":
        return [CypherQuery("most active investors in sector", f"""
            MATCH (c:Company)-[r:INVESTED_BY]->(i:Investor)
            WHERE c.is_startup AND {topic_filter('c')}
              AND ($date_from IS NULL OR r.last_round_date >= date($date_from))
            WITH i, count(DISTINCT c) AS startups_backed, sum(r.rounds) AS rounds_participated,
                 sum(CASE WHEN r.lead THEN 1 ELSE 0 END) AS rounds_led,
                 collect(DISTINCT c.name)[..8] AS portfolio
            RETURN i.name AS investor, i.type AS investor_type, startups_backed, rounds_participated, rounds_led,
                   portfolio
            ORDER BY startups_backed DESC, rounds_led DESC, i.quality DESC LIMIT $limit""",
                            {"terms": terms, "date_from": ents.date_from, "limit": lim})]

    if intent == "investor_portfolio" and investors:
        return [CypherQuery("investor portfolio", f"""
            MATCH (c:Company)-[r:INVESTED_BY]->(i:Investor) WHERE i.id IN $ids AND {topic_filter('c')}
            RETURN i.name AS investor, c.name AS company, c.sector AS sector, r.lead AS lead, r.rounds AS rounds,
                   c.total_funding AS company_total_funding, c AS c, r AS r, i AS i
            ORDER BY coalesce(c.total_funding, 0) DESC LIMIT $limit""",
                            {"ids": investors, "terms": terms, "limit": lim})]

    if intent == "founder_background" and ents.employers:
        return [CypherQuery("startups founded by former employees (multi-hop)", f"""
            MATCH (e:Entity) WHERE e.id IN $employer_ids
            OPTIONAL MATCH (e)-[:ACQUIRED]->(sub:Company)
            WITH collect(DISTINCT e) + collect(DISTINCT sub) AS employers
            UNWIND employers AS emp
            MATCH p = (c:Company)-[:FOUNDED_BY]->(f:Founder)-[:WORKED_AT]->(emp)
            WHERE c.is_startup AND NOT c IN employers AND {topic_filter('c')}
            WITH c, collect(DISTINCT f.name) AS founders, collect(DISTINCT emp.name) AS former_employers,
                 collect(p)[..3] AS paths
            RETURN c.name AS company, c.sector AS sector, founders, former_employers,
                   c.total_funding AS total_funding, paths
            ORDER BY coalesce(c.total_funding, 0) DESC LIMIT $limit""",
                            {"employer_ids": ids(ents.employers), "terms": terms, "limit": lim})]

    if intent == "founders_of" and (companies or ents.founders):
        return [CypherQuery("founders", """
            MATCH (c:Company)-[r:FOUNDED_BY]->(f:Founder)
            WHERE c.id IN $company_ids OR f.id IN $founder_ids
            OPTIONAL MATCH (f)-[w:WORKED_AT]->(e)
            WITH c, r, f, collect(w) AS w, collect(e) AS e
            RETURN c.name AS company, f.name AS founder, f.background AS background,
                   [x IN e | x.name] AS previous_employers, c AS c, r AS r, f AS f, w AS worked, e AS employers
            LIMIT $limit""", {"company_ids": companies, "founder_ids": ids(ents.founders), "limit": lim})]

    if intent == "funding_search":
        return [CypherQuery("funding rounds filter", f"""
            MATCH (c:Company)-[raised:RAISED]->(r:FundingRound)
            WHERE (size($round_types) = 0 OR r.round_type IN $round_types)
              AND ($date_from IS NULL OR r.date >= date($date_from))
              AND ($date_to IS NULL OR r.date <= date($date_to))
              AND (size($company_ids) = 0 OR c.id IN $company_ids)
              AND {topic_filter('c')}
            OPTIONAL MATCH (r)-[ri:INVESTED_BY]->(i:Investor)
            WITH c, raised, r, collect(ri) AS ris, collect(i) AS invs
            RETURN c.name AS company, c.sector AS sector, r.round_type AS round_type, r.amount AS amount,
                   toString(r.date) AS date, [x IN invs | x.name] AS investors, c AS c, raised AS raised, r AS r,
                   ris AS round_investments, invs AS investor_nodes
            ORDER BY r.date DESC LIMIT $limit""",
                            {"round_types": ents.round_types, "date_from": ents.date_from,
                             "date_to": ents.date_to, "company_ids": companies, "terms": terms, "limit": lim})]

    if intent == "acquisitions":
        return [CypherQuery("acquisitions", """
            MATCH (a:Company)-[r:ACQUIRED]->(b:Company)
            WHERE size($ids) = 0 OR a.id IN $ids OR b.id IN $ids
            RETURN a.name AS acquirer, b.name AS target, toString(r.date) AS date, r.amount AS amount,
                   a AS a, r AS r, b AS b
            ORDER BY r.date DESC LIMIT $limit""", {"ids": companies + investors, "limit": lim})]

    if intent == "technology_users" and ents.technologies:
        return [CypherQuery("technology users", """
            MATCH (c:Company)-[r:USES_TECH]->(t:Technology) WHERE t.id IN $ids
            RETURN t.name AS technology, c.name AS company, c.sector AS sector, c.total_funding AS total_funding,
                   c AS c, r AS r, t AS t
            ORDER BY coalesce(c.total_funding, 0) DESC LIMIT $limit""",
                            {"ids": ids(ents.technologies), "limit": lim})]

    if intent == "relationship":
        entity_ids = ids(ents.all_entities())
        if len(entity_ids) >= 2:
            return [
                CypherQuery("direct relationships", """
                    MATCH (a:Entity)-[r]->(b:Entity)
                    WHERE a.id IN $ids AND b.id IN $ids AND NOT type(r) IN ['MENTIONED_IN', 'RAISED']
                    RETURN a.name AS from, type(r) AS relationship, b.name AS to,
                           properties(r) AS details, a AS a, r AS r, b AS b""", {"ids": entity_ids}),
                CypherQuery("shortest connecting paths", """
                    UNWIND $ids AS x UNWIND $ids AS y
                    WITH x, y WHERE x < y
                    MATCH (a:Entity {id: x}), (b:Entity {id: y})
                    OPTIONAL MATCH p = allShortestPaths((a)-[*..3]-(b))
                    WHERE all(n IN nodes(p) WHERE n:Company OR n:Investor OR n:Founder)
                      AND none(rel IN relationships(p) WHERE type(rel) IN ['MENTIONED_IN', 'RAISED'])
                    WITH a, b, collect(p)[..3] AS paths
                    RETURN a.name AS from, b.name AS to, paths""", {"ids": entity_ids}),
            ]

    if intent in ("company_overview", "compare") and (companies or investors or ents.founders):
        entity_ids = companies or investors or ids(ents.founders)
        return [CypherQuery("company profile", COMPANY_SUMMARY, {"ids": entity_ids}),
                neighborhood_query(entity_ids, per_node=15)]

    if intent == "recommendation":
        return [CypherQuery("candidate startups", f"""
            MATCH (c:Company)
            WHERE c.is_startup AND {NOT_ACQUIRED} AND {topic_filter('c')}
            RETURN c.id AS id, c.name AS company, c.sector AS sector, c.total_funding AS total_funding,
                   c.employee_growth_pct AS employee_growth_pct, [(c)-[:INVESTED_BY]->(i) | i.name] AS investors,
                   c AS c
            ORDER BY coalesce(c.total_funding, 0) DESC LIMIT 100""", {"terms": terms})]

    return []


# ---------------------------------------------------------------- validation

WRITE_CLAUSES = re.compile(
    r"\b(CREATE|MERGE|DELETE|DETACH|SET|REMOVE|DROP|FOREACH|LOAD\s+CSV|GRANT|DENY|REVOKE|ALTER|RENAME|"
    r"START|STOP|TERMINATE|USE|FINISH)\b",
    re.I,
)
CALL_PROC = re.compile(r"\bCALL\s+(?!\{|\()([\w.]+)", re.I)
ALLOWED_PROCEDURES = {"db.index.fulltext.querynodes", "db.labels", "db.relationshiptypes", "db.schema.visualization"}


class UnsafeCypherError(ValueError):
    pass


def _strip_literals(cypher: str) -> str:
    cypher = re.sub(r"//.*?$|/\*.*?\*/", " ", cypher, flags=re.S | re.M)
    return re.sub(r"'(?:\\.|[^'\\])*'|\"(?:\\.|[^\"\\])*\"|`[^`]*`", "''", cypher)


def validate_cypher(cypher: str, max_limit: int = 100) -> str:
    """Reject anything that is not a single read-only query; enforce a LIMIT."""
    text = cypher.strip().rstrip(";").strip()
    text = re.sub(r"^```(?:cypher)?|```$", "", text, flags=re.I).strip()
    bare = _strip_literals(text)
    if ";" in bare:
        raise UnsafeCypherError("multiple statements are not allowed")
    if m := WRITE_CLAUSES.search(bare):
        raise UnsafeCypherError(f"write/admin clause not allowed: {m.group(1).upper()}")
    for proc in CALL_PROC.findall(bare):
        if proc.lower() not in ALLOWED_PROCEDURES:
            raise UnsafeCypherError(f"procedure not allowed: {proc}")
    if not re.match(r"^(MATCH|OPTIONAL\s+MATCH|WITH|UNWIND|RETURN|CALL)\b", bare, re.I):
        raise UnsafeCypherError("query must start with MATCH/OPTIONAL MATCH/WITH/UNWIND/RETURN")
    if not re.search(r"\bRETURN\b", bare, re.I):
        raise UnsafeCypherError("query must RETURN results")
    limit = re.search(r"\bLIMIT\s+(\d+)\s*$", bare, re.I)
    if not limit:
        text = f"{text} LIMIT {max_limit}"
    elif int(limit.group(1)) > max_limit:
        text = re.sub(r"\bLIMIT\s+\d+\s*$", f"LIMIT {max_limit}", text, flags=re.I)
    return text


CYPHER_PROMPT = """You are a Neo4j Cypher expert for a startup intelligence knowledge graph.

{schema}

Rules:
- Write ONE read-only Cypher query (no CREATE/MERGE/SET/DELETE/CALL procedures).
- Match entities by their `id` property using the resolved ids below; never invent ids.
- Treat COMPETES_WITH and PARTNERS_WITH as undirected: (a)-[:COMPETES_WITH]-(b).
- Return readable scalar columns (names, amounts, dates via toString()) and also return the
  matched nodes/relationships or paths (as columns) so the result can be visualised.
- End with LIMIT {limit}.

Resolved entities (name -> id): {entities}
Filters: {filters}

Question: {question}

Respond with only the Cypher query."""
