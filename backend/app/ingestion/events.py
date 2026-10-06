"""Event detection for the news intelligence pipeline.

Detects funding, acquisition, partnership and product-launch events in article
text. A regex extractor always runs; when an LLM is configured its structured
extraction is used instead (falling back to regex on failure).
"""

from __future__ import annotations

import logging
import re
from dataclasses import asdict, dataclass, field
from typing import Any, Literal

from pydantic import BaseModel, Field

log = logging.getLogger(__name__)

EventType = Literal["funding", "acquisition", "partnership", "product_launch"]

_NAME_TOKEN = r"(?:[A-Z][\w&'+-]*(?:\.[A-Za-z]+)*(?::[a-z]+)?|AI|Labs?|a16z|\d+[A-Za-z]+)"
NAME = rf"{_NAME_TOKEN}(?:\s+{_NAME_TOKEN}){{0,3}}"
AMOUNT = r"(?P<currency>[$€£])\s?(?P<amount>\d+(?:[.,]\d+)?)\s*(?P<unit>billion|million|bn|mn|[BMK])?\b"
ROUND = r"(?P<round>pre-?seed|seed|series\s+[a-k]|growth)"

FUNDING_RE = re.compile(
    rf"(?P<company>{NAME})\s+(?:has\s+)?(?:raises|raised|secures|secured|closes|closed|lands|landed|nabs|bags|"
    rf"announces|announced|gets|got)\s+(?:a\s+|an\s+|its\s+)?(?:new\s+)?{AMOUNT}(?:\s+\w+){{0,4}}?"
    rf"(?:\s+{ROUND})?",
)
ROUND_ANYWHERE = re.compile(rf"\b{ROUND}\b", re.I)
LEAD_RE = re.compile(rf"\bled by\s+(?P<lead>{NAME})")
PARTICIPANTS_RE = re.compile(r"(?:participation from|backed by|investors including|alongside)\s+(?P<list>[^.;]+)")
ACQUISITION_RE = re.compile(
    rf"(?P<acquirer>{NAME})\s+(?:acquires|acquired|has acquired|to acquire|will acquire|buys|bought|to buy|"
    rf"snaps up|agrees to (?:buy|acquire)|agreed to (?:buy|acquire)|completes acquisition of|completed "
    rf"(?:its )?acquisition of)\s+(?P<target>{NAME})"
)
ACQ_AMOUNT_RE = re.compile(rf"\bfor\s+(?:about\s+|around\s+|roughly\s+)?{AMOUNT}")
PARTNERSHIP_RE = re.compile(
    rf"(?P<a>{NAME})\s+(?:partners|partnered|teams up|teamed up|joins forces|signs (?:a\s+)?(?:\w+\s+)?"
    rf"(?:partnership|deal)|forms (?:a\s+)?(?:\w+\s+)?partnership)\s+with\s+(?P<b>{NAME})"
)
LAUNCH_RE = re.compile(
    rf"(?P<company>{NAME})\s+(?:launches|launched|unveils|unveiled|releases|released|debuts|introduces|"
    rf"rolls out|announces)\s+(?P<product>[^,.;:]{{3,80}})"
)

STOP_PREFIXES = re.compile(r"^(?:exclusive|report|breaking|update|scoop|watch|video)\s*[:\-–]\s*", re.I)
GENERIC_NAMES = {"The", "A", "An", "This", "It", "Startup", "Company", "Report", "Sources", "AI", "Its", "Why",
                 "How", "What", "Today", "Here"}


@dataclass
class Event:
    type: EventType
    company: str | None = None          # funding/launch subject; acquirer; partnership side A
    counterparty: str | None = None     # acquisition target; partnership side B
    amount: float | None = None
    round_type: str | None = None
    lead_investors: list[str] = field(default_factory=list)
    investors: list[str] = field(default_factory=list)
    product: str | None = None
    evidence: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def parse_amount(amount: str, unit: str | None, currency: str = "$") -> float:
    value = float(amount.replace(",", ""))
    unit = (unit or "").lower()
    mult = {"billion": 1e9, "bn": 1e9, "b": 1e9, "million": 1e6, "mn": 1e6, "m": 1e6, "k": 1e3}.get(unit, 1)
    fx = {"€": 1.08, "£": 1.27}.get(currency, 1.0)  # rough USD normalisation
    return round(value * mult * fx, -3)


def normalise_round(raw: str | None) -> str | None:
    if not raw:
        return None
    raw = raw.lower()
    if raw.startswith("series"):
        return "Series " + raw.split()[-1].upper()
    if "seed" in raw:
        return "Pre-Seed" if raw.startswith("pre") else "Seed"
    return "Growth"


def _clean_name(name: str | None) -> str | None:
    if not name:
        return None
    name = re.sub(r"['’]s$", "", name.strip(" ,.;:"))
    words = name.split()
    while words and words[0] in GENERIC_NAMES:
        words = words[1:]
    return " ".join(words) or None


def _split_names(text: str) -> list[str]:
    parts = re.split(r",\s*|\s+and\s+|\s*&\s*", text)
    names = []
    for p in parts:
        m = re.match(NAME, p.strip())
        if m and (n := _clean_name(m.group(0))):
            names.append(n)
    return names


def extract_events_regex(title: str, body: str = "") -> list[Event]:
    events: list[Event] = []
    title = STOP_PREFIXES.sub("", title.strip())
    text = f"{title}. {body}".strip()
    sentences = re.split(r"(?<=[.!?])\s+", text)

    for m in FUNDING_RE.finditer(text):
        company = _clean_name(m.group("company"))
        if not company:
            continue
        sentence = next((s for s in sentences if m.group(0)[:40] in s), m.group(0))
        window = text[m.start():m.start() + 700]  # round details often follow in the next sentences
        lead = LEAD_RE.search(window)
        parts = PARTICIPANTS_RE.search(window)
        round_type = normalise_round(m.group("round")) or normalise_round(
            (r := ROUND_ANYWHERE.search(window)) and r.group(1))
        events.append(Event(
            type="funding", company=company,
            amount=parse_amount(m.group("amount"), m.group("unit"), m.group("currency")),
            round_type=round_type, lead_investors=_split_names(lead.group("lead")) if lead else [],
            investors=_split_names(parts.group("list")) if parts else [], evidence=sentence[:300],
        ))
        break  # one funding event per article

    if m := ACQUISITION_RE.search(text):
        acquirer, target = _clean_name(m.group("acquirer")), _clean_name(m.group("target"))
        if acquirer and target and acquirer != target:
            amt = ACQ_AMOUNT_RE.search(text[m.start():m.start() + 300])
            events.append(Event(
                type="acquisition", company=acquirer, counterparty=target,
                amount=parse_amount(amt.group("amount"), amt.group("unit"), amt.group("currency")) if amt else None,
                evidence=m.group(0)[:300],
            ))

    if m := PARTNERSHIP_RE.search(text):
        a, b = _clean_name(m.group("a")), _clean_name(m.group("b"))
        if a and b and a != b:
            events.append(Event(type="partnership", company=a, counterparty=b, evidence=m.group(0)[:300]))

    if not events and (m := LAUNCH_RE.search(title)):
        company = _clean_name(m.group("company"))
        if company:
            events.append(Event(type="product_launch", company=company, product=m.group("product").strip(),
                                evidence=m.group(0)[:300]))
    return events


class EventOut(BaseModel):
    type: EventType
    company: str = Field(description="Funded company / acquirer / launching company / first partner")
    counterparty: str | None = Field(default=None, description="Acquired company or second partner")
    amount_usd: float | None = None
    round_type: str | None = Field(default=None, description="Seed, Series A, Series B, ... or Growth")
    lead_investors: list[str] = Field(default_factory=list)
    investors: list[str] = Field(default_factory=list)
    product: str | None = None


class EventsOut(BaseModel):
    events: list[EventOut] = Field(default_factory=list)


async def extract_events(title: str, body: str, llm: Any | None = None) -> list[Event]:
    if llm is not None:
        prompt = ("Extract startup events (funding, acquisition, partnership, product_launch) explicitly stated "
                  "in this news article. Return an empty list if none. Do not guess amounts.\n\n"
                  f"Title: {title}\n\n{body[:4000]}")
        try:
            out: EventsOut = await llm.with_structured_output(EventsOut).ainvoke(prompt)
            return [Event(type=e.type, company=e.company, counterparty=e.counterparty, amount=e.amount_usd,
                          round_type=normalise_round(e.round_type) if e.round_type else None,
                          lead_investors=e.lead_investors, investors=e.investors, product=e.product,
                          evidence=title) for e in out.events]
        except Exception as exc:
            log.warning("LLM event extraction failed, using regex: %s", exc)
    return extract_events_regex(title, body)
