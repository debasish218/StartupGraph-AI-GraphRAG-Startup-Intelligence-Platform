"""Lightweight lexicon sentiment scorer for business news (-1 .. 1)."""

import re

POSITIVE = {
    "raise", "raises", "raised", "growth", "grow", "growing", "grew", "strong", "record", "launch", "launches",
    "launched", "expand", "expands", "expansion", "partnership", "partners", "win", "wins", "surge", "surges",
    "profitable", "profit", "milestone", "leading", "leader", "lead", "rapid", "rapidly", "breakthrough",
    "success", "successful", "accelerate", "momentum", "demand", "adoption", "largest", "funding", "backed",
    "valuation", "innovative", "improve", "improved", "boost", "doubled", "tripled", "outperform",
}
NEGATIVE = {
    "layoff", "layoffs", "cut", "cuts", "lawsuit", "lawsuits", "sued", "decline", "declining", "declined",
    "turmoil", "resign", "resigns", "resigned", "setback", "pressure", "concern", "concerns", "loss", "losses",
    "shutdown", "shut", "paused", "risk", "risks", "struggle", "struggles", "fraud", "investigation", "probe",
    "departure", "departures", "burn", "downturn", "fine", "fined", "breach", "outage", "delay", "delayed",
    "exodus", "bankrupt", "bankruptcy", "slump", "warning", "scrutiny", "reduced", "reduce",
}
NEGATORS = {"not", "no", "never", "without", "despite"}


def score_sentiment(text: str) -> float:
    tokens = re.findall(r"[a-z']+", text.lower())
    pos = neg = 0
    for i, tok in enumerate(tokens):
        polarity = 1 if tok in POSITIVE else -1 if tok in NEGATIVE else 0
        if not polarity:
            continue
        if any(t in NEGATORS for t in tokens[max(0, i - 2):i]):
            polarity = -polarity
        if polarity > 0:
            pos += 1
        else:
            neg += 1
    if pos + neg == 0:
        return 0.0
    return round((pos - neg) / (pos + neg + 1), 3)
