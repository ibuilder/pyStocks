"""Built-in scan definitions. Order here is the order shown in the UI dropdown."""
from __future__ import annotations

SCANS: list[dict] = [
    {"name": "Top Gainers", "filters": [], "sort": "pct_from_open", "desc": True, "min_bars": 3},
    {"name": "Top Losers", "filters": [], "sort": "pct_from_open", "desc": False, "min_bars": 3},
    {"name": "Unusual Volume (RVOL>1.5)",
     "filters": [{"field": "rvol", "op": ">", "value": 1.5}], "sort": "rvol", "desc": True},
    {"name": "Opening-Range Breakouts",
     "filters": [{"field": "above_or_high", "op": "is_true", "value": True},
                 {"field": "rvol", "op": ">", "value": 1.2}], "sort": "rvol", "desc": True},
    {"name": "Breakdowns (below OR)",
     "filters": [{"field": "below_or_low", "op": "is_true", "value": True}],
     "sort": "pct_from_open", "desc": False},
    {"name": "Oversold (RSI<35)",
     "filters": [{"field": "rsi14", "op": "<", "value": 35}], "sort": "rsi14", "desc": False},
    {"name": "Overbought (RSI>70)",
     "filters": [{"field": "rsi14", "op": ">", "value": 70}], "sort": "rsi14", "desc": True},
    {"name": "Above VWAP + EMA stack",
     "filters": [{"field": "pct_from_vwap", "op": ">", "value": 0},
                 {"field": "ema_stack_bull", "op": "is_true", "value": True}],
     "sort": "pct_from_open", "desc": True},
    {"name": "Positive News Movers",
     "filters": [{"field": "news_sentiment", "op": ">", "value": 0.2},
                 {"field": "rvol", "op": ">", "value": 1.0}], "sort": "news_sentiment", "desc": True},
    {"name": "Negative News Movers",
     "filters": [{"field": "news_sentiment", "op": "<", "value": -0.2},
                 {"field": "rvol", "op": ">", "value": 1.0}], "sort": "news_sentiment", "desc": False},
]

SCANS_BY_NAME = {s["name"]: s for s in SCANS}


def names() -> list[str]:
    return [s["name"] for s in SCANS]
