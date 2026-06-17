"""News sentiment tests (pure scorer)."""
from __future__ import annotations

from news.sentiment import score_text, score_headlines


def test_positive_and_negative():
    assert score_text("Company beats earnings, shares surge to record high")["score"] > 0.5
    assert score_text("Stock plunges on weak guidance, downgrade and lawsuit fears")["score"] < -0.5
    assert score_text("The company announced a new office location")["score"] == 0.0


def test_negation_flips():
    pos = score_text("strong growth")["score"]
    neg = score_text("not strong growth")["score"]
    assert pos > 0 >= neg  # "not strong" should not stay positive


def test_score_bounds_and_empty():
    s = score_text("beats beats beats surge rally")
    assert 0.0 <= s["score"] <= 1.0
    assert score_text("")["score"] == 0.0
    assert score_headlines([]) == {"sentiment": 0.0, "count": 0, "top_headline": None, "top_score": 0.0}


def test_aggregate_recency_weight():
    items = [
        {"title": "shares surge on record profit", "summary": ""},   # newest, positive
        {"title": "minor lawsuit concern", "summary": ""},           # older, negative
    ]
    agg = score_headlines(items)
    assert agg["count"] == 2
    assert agg["sentiment"] > 0          # newest positive dominates via recency weight
    assert agg["top_headline"] is not None
