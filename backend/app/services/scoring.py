"""Startup score model.

    Startup Score = 0.35 x Funding + 0.25 x News + 0.20 x Hiring + 0.20 x Investor Quality

Each component is normalised to 0..1 on an absolute scale (not relative to the
candidate set) so that scores are comparable across queries.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass

WEIGHTS = {"funding": 0.35, "news": 0.25, "hiring": 0.20, "investor_quality": 0.20}

FUNDING_FLOOR = 1e6    # $1M  -> 0
FUNDING_CEIL = 1e11    # $100B -> 1
HIRING_FLOOR = -20.0   # -20% headcount growth -> 0
HIRING_CEIL = 100.0    # +100% -> 1


def _clamp(x: float) -> float:
    return max(0.0, min(1.0, x))


def funding_score(total_funding: float | None) -> float:
    if not total_funding or total_funding <= 0:
        return 0.0
    lo, hi = math.log10(FUNDING_FLOOR), math.log10(FUNDING_CEIL)
    return _clamp((math.log10(total_funding) - lo) / (hi - lo))


def news_score(avg_sentiment: float | None, article_count: int = 0) -> float:
    """Map -1..1 sentiment to 0..1, shrunk toward neutral when coverage is thin."""
    if avg_sentiment is None or article_count <= 0:
        return 0.5
    raw = (avg_sentiment + 1) / 2
    weight = article_count / (article_count + 1)
    return _clamp(0.5 + (raw - 0.5) * weight)


def hiring_score(employee_growth_pct: float | None) -> float:
    if employee_growth_pct is None:
        return 0.5
    return _clamp((employee_growth_pct - HIRING_FLOOR) / (HIRING_CEIL - HIRING_FLOOR))


def investor_quality_score(qualities: list[float]) -> float:
    """Mean quality of the top-3 investors plus a small bonus for investor breadth."""
    qs = sorted((q for q in qualities if q is not None), reverse=True)
    if not qs:
        return 0.0
    top = qs[:3]
    return _clamp(0.85 * (sum(top) / len(top)) + 0.15 * min(len(qs), 10) / 10)


@dataclass
class StartupScore:
    company_id: str
    name: str
    funding: float
    news: float
    hiring: float
    investor_quality: float
    score: float
    total_funding: float | None = None
    employee_growth_pct: float | None = None
    news_articles: int = 0
    investors: list[str] | None = None
    sector: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


def compute_score(*, company_id: str, name: str, total_funding: float | None, avg_sentiment: float | None,
                  article_count: int, employee_growth_pct: float | None, investor_qualities: list[float],
                  investors: list[str] | None = None, sector: str | None = None) -> StartupScore:
    f = funding_score(total_funding)
    n = news_score(avg_sentiment, article_count)
    h = hiring_score(employee_growth_pct)
    q = investor_quality_score(investor_qualities)
    total = (WEIGHTS["funding"] * f + WEIGHTS["news"] * n + WEIGHTS["hiring"] * h
             + WEIGHTS["investor_quality"] * q)
    return StartupScore(
        company_id=company_id, name=name, funding=round(f, 3), news=round(n, 3), hiring=round(h, 3),
        investor_quality=round(q, 3), score=round(total, 3), total_funding=total_funding,
        employee_growth_pct=employee_growth_pct, news_articles=article_count, investors=investors, sector=sector,
    )
