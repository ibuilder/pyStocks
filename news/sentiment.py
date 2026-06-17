"""Transparent finance-sentiment scoring (lexicon baseline).

A compact Loughran-McDonald-style finance word list. `score_text` returns a net
sentiment in [-1, 1] with simple negation handling ("not strong" flips). This is a
deliberately explainable baseline; swap in FinBERT/an LLM by replacing `score_text`
(keep the signature). Lexicon sentiment is weaker than FinBERT — treat scores as a
rough tilt, not ground truth.
"""
from __future__ import annotations

import re

POSITIVE = {
    "beat", "beats", "surge", "surged", "soar", "soars", "soared", "rally", "rallies",
    "jump", "jumps", "jumped", "gain", "gains", "gained", "rise", "rises", "rose",
    "upgrade", "upgraded", "outperform", "outperforms", "strong", "strength", "record",
    "growth", "grew", "profit", "profits", "profitable", "bullish", "boost", "boosted",
    "win", "wins", "winning", "approval", "approved", "breakthrough", "expand",
    "expansion", "raise", "raised", "raises", "topped", "tops", "exceed", "exceeds",
    "exceeded", "optimistic", "positive", "improve", "improved", "improving", "rebound",
    "recovery", "robust", "accelerate", "accelerated", "milestone", "dividend",
    "buyback", "upbeat", "momentum", "leads", "leading", "demand", "high", "higher",
    "success", "successful", "lucrative", "advantage", "favorable",
}

NEGATIVE = {
    "miss", "misses", "missed", "plunge", "plunges", "plunged", "drop", "drops",
    "dropped", "fall", "falls", "fell", "decline", "declines", "declined", "slump",
    "slumps", "downgrade", "downgraded", "underperform", "weak", "weakness", "loss",
    "losses", "bearish", "cut", "cuts", "slash", "slashed", "warn", "warns", "warning",
    "lawsuit", "probe", "investigation", "fraud", "recall", "halt", "halted", "delay",
    "delayed", "concern", "concerns", "fears", "risk", "risks", "risky", "selloff",
    "tumble", "tumbled", "crash", "crashed", "sink", "sinks", "sank", "disappoint",
    "disappointing", "disappointed", "layoff", "layoffs", "bankruptcy", "default",
    "deficit", "shortfall", "negative", "pessimistic", "slowdown", "weaker", "lower",
    "struggle", "struggles", "struggling", "pressure", "pressured", "downturn",
    "scandal", "subpoena", "penalty", "fined", "fine", "glut", "oversupply", "guidance",
}

NEGATORS = {"not", "no", "never", "without", "fails", "fail", "failed", "less", "lacks", "lack"}
_WORD = re.compile(r"[a-z']+")


def score_text(text: str) -> dict:
    """Return {score in [-1,1], pos, neg} for a headline / short text."""
    if not text:
        return {"score": 0.0, "pos": 0, "neg": 0}
    words = _WORD.findall(text.lower())
    pos = neg = 0
    for i, w in enumerate(words):
        negated = i > 0 and words[i - 1] in NEGATORS
        if w in POSITIVE:
            neg, pos = (neg + 1, pos) if negated else (neg, pos + 1)
        elif w in NEGATIVE:
            pos, neg = (pos + 1, neg) if negated else (pos, neg + 1)
    total = pos + neg
    score = (pos - neg) / total if total else 0.0
    return {"score": round(score, 4), "pos": pos, "neg": neg}


def score_headlines(items: list[dict]) -> dict:
    """Aggregate sentiment across a ticker's headlines (recency-weighted)."""
    if not items:
        return {"sentiment": 0.0, "count": 0, "top_headline": None, "top_score": 0.0}
    scored = []
    for idx, it in enumerate(items):
        text = (it.get("title") or "") + ". " + (it.get("summary") or "")
        s = score_text(text)
        weight = 1.0 / (1 + idx)  # newer headlines (already sorted) weigh more
        scored.append((s["score"], weight, it.get("title"), s))
    wsum = sum(w for _, w, _, _ in scored) or 1.0
    agg = sum(sc * w for sc, w, _, _ in scored) / wsum
    # most strongly-signed headline for display
    top = max(scored, key=lambda x: abs(x[0]))
    return {
        "sentiment": round(agg, 4),
        "count": len(items),
        "top_headline": top[2],
        "top_score": top[0],
    }
