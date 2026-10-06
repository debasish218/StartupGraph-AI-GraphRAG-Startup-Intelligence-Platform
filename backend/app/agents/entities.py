"""Entity extraction (Agent 2).

The rule-based extractor resolves mentions against a gazetteer built from the
knowledge graph, so every extracted entity maps to a real node id. The LLM
extractor (when enabled) proposes names that are then resolved through the same
gazetteer, which prevents hallucinated entities from reaching Cypher.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Any

# Canonical topic -> lowercase terms matched against Company.sector, Company.tags and Technology.name
TOPICS: dict[str, list[str]] = {
    "Computer Vision": ["computer vision", "video understanding", "video ai"],
    "Generative AI": ["generative ai", "diffusion models", "generative video"],
    "Large Language Models": ["large language models", "llm", "foundation models"],
    "Robotics": ["robotics", "humanoid robots", "embodied ai"],
    "Video AI": ["video understanding", "generative video", "video ai"],
    "Data Labeling": ["data labeling"],
    "AI Search": ["ai search", "search"],
    "MLOps": ["mlops"],
    "Open Source": ["open source", "open-source models"],
    "AI Safety": ["ai safety"],
    "AI Agents": ["ai agents"],
    "AI Infrastructure": ["ai infrastructure", "gpu orchestration", "mlops"],
    "Data Infrastructure": ["data infrastructure", "data platform", "data lakehouse"],
    "Enterprise AI": ["enterprise ai"],
    "Artificial Intelligence": [
        "artificial intelligence", "computer vision", "generative ai", "large language models",
        "ai infrastructure", "robotics", "mlops", "multimodal ai",
    ],
}

TOPIC_PATTERNS: list[tuple[str, str]] = [
    (r"computer[- ]vision|\bcv\b|visual ai|image recognition", "Computer Vision"),
    (r"generative ai|gen[- ]?ai|image generation|text[- ]to[- ]image", "Generative AI"),
    (r"\bllms?\b|large language models?|foundation models?|frontier (?:ai )?labs?", "Large Language Models"),
    (r"robotics|humanoids?|embodied ai|robots?\b", "Robotics"),
    (r"video (?:ai|understanding|generation)|generative video", "Video AI"),
    (r"data[- ]labell?ing|annotation", "Data Labeling"),
    (r"ai search|answer engines?|search engines?", "AI Search"),
    (r"\bmlops\b|ml infrastructure", "MLOps"),
    (r"open[- ]source|open[- ]weights?", "Open Source"),
    (r"ai safety|alignment", "AI Safety"),
    (r"ai agents?|agentic", "AI Agents"),
    (r"ai infrastructure|gpu|compute infrastructure", "AI Infrastructure"),
    (r"data infrastructure|data platforms?|lakehouse", "Data Infrastructure"),
    (r"enterprise ai", "Enterprise AI"),
    (r"\bai\b|artificial intelligence|machine learning|\bml\b", "Artificial Intelligence"),
]

ROUND_PATTERN = re.compile(r"\b(pre-?seed|seed|series\s+[a-k]|growth(?:\s+round)?)\b", re.I)
DATE_PATTERN = re.compile(
    r"\b(after|since|post|from|starting|before|prior to|until|through|in|during)\s+(?:the\s+year\s+)?((?:19|20)\d\d)\b",
    re.I,
)
TOP_N_PATTERN = re.compile(r"\btop\s+(\d{1,2})\b", re.I)
EMPLOYER_BEFORE = re.compile(
    r"(?:\bex[- ]|\bformer(?:ly)?(?: at)? |\bworked (?:at|for) |\balumni of |\balums? of |\bleft |\bfrom )$", re.I
)
EMPLOYER_AFTER = re.compile(r"^(?:'s)?\s*(?:alumni|alums|veterans|employees|engineers|researchers)\b", re.I)

# Single common words that are also entity names/aliases: only match them when capitalised.
AMBIGUOUS_WORDS = {
    "scale", "figure", "thrive", "stability", "search", "inflection", "adept", "spark", "index", "runway",
    "perplexity", "robotics", "embeddings", "addition", "meta", "apple", "character", "insight", "fidelity",
    "accel", "valor", "mistral", "io",
}


@dataclass
class CatalogEntry:
    id: str
    name: str
    labels: list[str]
    surface: str  # the name/alias string that is matched


@dataclass
class ExtractedEntities:
    companies: list[dict[str, str]] = field(default_factory=list)
    investors: list[dict[str, str]] = field(default_factory=list)
    founders: list[dict[str, str]] = field(default_factory=list)
    technologies: list[dict[str, str]] = field(default_factory=list)
    employers: list[dict[str, str]] = field(default_factory=list)
    topics: list[str] = field(default_factory=list)
    round_types: list[str] = field(default_factory=list)
    date_from: str | None = None
    date_to: str | None = None
    date_strict: bool = False  # True when "after YEAR" was interpreted as strictly after
    limit: int | None = None

    def all_entities(self) -> list[dict[str, str]]:
        seen, out = set(), []
        for group in (self.companies, self.investors, self.founders, self.technologies, self.employers):
            for e in group:
                if e["id"] not in seen:
                    seen.add(e["id"])
                    out.append(e)
        return out

    def topic_terms(self) -> list[str]:
        terms: list[str] = []
        for t in self.topics:
            terms.extend(TOPICS.get(t, [t.lower()]))
        for tech in self.technologies:
            terms.append(tech["name"].lower())
        return sorted(set(terms))

    def to_dict(self) -> dict[str, Any]:
        return {
            "companies": self.companies, "investors": self.investors, "founders": self.founders,
            "technologies": self.technologies, "employers": self.employers, "topics": self.topics,
            "round_types": self.round_types, "date_from": self.date_from, "date_to": self.date_to,
            "date_strict": self.date_strict, "limit": self.limit,
        }


class EntityCatalog:
    """Gazetteer of graph entities, matched longest-surface-first."""

    def __init__(self, rows: list[dict[str, Any]] | None = None):
        self.entries: list[CatalogEntry] = []
        self.by_id: dict[str, CatalogEntry] = {}
        self.load(rows or [])

    def load(self, rows: list[dict[str, Any]]) -> None:
        self.by_id = {}
        entries = []
        for r in rows:
            if not r.get("name"):
                continue
            base = CatalogEntry(id=r["id"], name=r["name"], labels=r.get("labels") or [], surface=r["name"])
            self.by_id[r["id"]] = base
            for surface in {r["name"], *(r.get("aliases") or [])}:
                if len(surface) >= 2:
                    entries.append(CatalogEntry(base.id, base.name, base.labels, surface))
        self.entries = sorted(entries, key=lambda e: len(e.surface), reverse=True)

    def __len__(self) -> int:
        return len(self.by_id)

    def resolve(self, name: str, labels: set[str] | None = None) -> CatalogEntry | None:
        """Resolve a free-text name (e.g. proposed by an LLM) to a catalog entry."""
        needle = name.strip().lower()
        best, best_score = None, 0.0
        for e in self.entries:
            if labels and not labels.intersection(e.labels):
                continue
            s = e.surface.lower()
            if s == needle:
                return self.by_id[e.id]
            score = SequenceMatcher(None, needle, s).ratio()
            if score > best_score:
                best, best_score = e, score
        return self.by_id[best.id] if best and best_score >= 0.88 else None

    def find_mentions(self, text: str) -> list[tuple[CatalogEntry, int, int]]:
        taken: list[tuple[int, int]] = []
        found: list[tuple[CatalogEntry, int, int]] = []
        for e in self.entries:
            surface = e.surface
            case_sensitive = len(surface) <= 3 or surface.lower() in AMBIGUOUS_WORDS
            flags = 0 if case_sensitive else re.I
            # Hyphens are allowed before a name ("ex-Google") but not inside a longer token after it.
            pattern = r"(?<!\w)" + re.escape(surface) + r"(?![\w]|-\w)"
            for m in re.finditer(pattern, text, flags):
                if case_sensitive and surface.lower() in AMBIGUOUS_WORDS and not m.group(0)[0].isupper():
                    continue
                if any(m.start() < b and a < m.end() for a, b in taken):
                    continue
                taken.append((m.start(), m.end()))
                found.append((self.by_id[e.id], m.start(), m.end()))
        return sorted(found, key=lambda x: x[1])


def _entity_dict(e: CatalogEntry) -> dict[str, str]:
    return {"id": e.id, "name": e.name, "type": _primary_type(e.labels)}


def _primary_type(labels: list[str]) -> str:
    for lbl in ("Founder", "Technology", "Company", "Investor"):
        if lbl in labels:
            return lbl
    return labels[0] if labels else "Entity"


def _add(group: list[dict[str, str]], item: dict[str, str]) -> None:
    if all(x["id"] != item["id"] for x in group):
        group.append(item)


def extract_entities_rules(question: str, catalog: EntityCatalog) -> ExtractedEntities:
    out = ExtractedEntities()
    mention_spans: list[tuple[int, int]] = []

    for entry, start, end in catalog.find_mentions(question):
        mention_spans.append((start, end))
        item = _entity_dict(entry)
        before, after = question[max(0, start - 20):start], question[end:end + 20]
        if EMPLOYER_BEFORE.search(before) or EMPLOYER_AFTER.match(after):
            _add(out.employers, item)
            continue
        labels = set(entry.labels)
        if "Founder" in labels:
            _add(out.founders, item)
        elif "Technology" in labels and entry.name in TOPICS:
            if entry.name not in out.topics:
                out.topics.append(entry.name)
        elif "Technology" in labels:
            _add(out.technologies, item)
        elif "Company" in labels and "Investor" in labels:
            # Corporates (Microsoft, Nvidia...) play both roles; keep them as companies, and also as
            # investors when the question is about funding.
            _add(out.companies, item)
            if re.search(r"invest|fund|back|portfolio", question, re.I):
                _add(out.investors, item)
        elif "Investor" in labels:
            _add(out.investors, item)
        else:
            _add(out.companies, item)

    # Topics, ignoring text already consumed by entity names (e.g. "Figure AI")
    masked = list(question)
    for a, b in mention_spans:
        masked[a:b] = " " * (b - a)
    masked_text = "".join(masked)
    topic_spans: list[tuple[int, int]] = []
    for pattern, topic in TOPIC_PATTERNS:
        for m in re.finditer(pattern, masked_text, re.I):
            if any(m.start() < b and a < m.end() for a, b in topic_spans):
                continue
            topic_spans.append((m.start(), m.end()))
            if topic not in out.topics:
                out.topics.append(topic)
    # The generic "AI" topic is dropped when a more specific topic is present.
    if len(out.topics) > 1 and "Artificial Intelligence" in out.topics:
        out.topics.remove("Artificial Intelligence")
    # Technologies matched as entities already act as topic filters.
    tech_names = {t["name"] for t in out.technologies}
    out.topics = [t for t in out.topics if t not in tech_names]

    for m in ROUND_PATTERN.finditer(question):
        raw = m.group(1).lower()
        if raw.startswith("series"):
            norm = "Series " + raw.split()[-1].upper()
        elif "seed" in raw:
            norm = "Pre-Seed" if raw.startswith("pre") else "Seed"
        else:
            norm = "Growth"
        if norm not in out.round_types:
            out.round_types.append(norm)

    for m in DATE_PATTERN.finditer(question):
        word, year = m.group(1).lower(), int(m.group(2))
        if word in ("after", "post"):
            out.date_from, out.date_strict = f"{year + 1}-01-01", True
        elif word in ("since", "from", "starting"):
            out.date_from = f"{year}-01-01"
        elif word in ("before", "prior to"):
            out.date_to = f"{year - 1}-12-31"
        elif word in ("until", "through"):
            out.date_to = f"{year}-12-31"
        else:  # in / during
            out.date_from, out.date_to = f"{year}-01-01", f"{year}-12-31"

    if m := TOP_N_PATTERN.search(question):
        out.limit = int(m.group(1))
    return out


def infer_topics(text: str) -> list[str]:
    """Sector topics mentioned in free text (specific topics win over generic AI)."""
    topics: list[str] = []
    for pattern, topic in TOPIC_PATTERNS:
        if re.search(pattern, text, re.I) and topic not in topics:
            topics.append(topic)
    if len(topics) > 1 and "Artificial Intelligence" in topics:
        topics.remove("Artificial Intelligence")
    return topics


def merge_llm_entities(rule: ExtractedEntities, llm: dict[str, Any], catalog: EntityCatalog) -> ExtractedEntities:
    """Merge LLM-proposed entity names (resolved through the catalog) into rule-based output."""
    groups = {
        "companies": ({"Company"}, rule.companies),
        "investors": ({"Investor"}, rule.investors),
        "founders": ({"Founder"}, rule.founders),
        "technologies": ({"Technology"}, rule.technologies),
        "employers": ({"Company", "Investor"}, rule.employers),
    }
    for key, (labels, target) in groups.items():
        for name in llm.get(key) or []:
            if entry := catalog.resolve(str(name), labels):
                _add(target, _entity_dict(entry))
    # An employer is not also a subject company of the question.
    employer_ids = {e["id"] for e in rule.employers}
    rule.companies = [c for c in rule.companies if c["id"] not in employer_ids]
    for t in llm.get("topics") or []:
        if t in TOPICS and t not in rule.topics:
            rule.topics.append(t)
    for r in llm.get("round_types") or []:
        if r not in rule.round_types:
            rule.round_types.append(r)
    rule.date_from = rule.date_from or llm.get("date_from")
    rule.date_to = rule.date_to or llm.get("date_to")
    return rule
