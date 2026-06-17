"""Scanner engine tests."""
from __future__ import annotations

from scanners.engine import run_scan
from scanners.library import SCANS_BY_NAME


SNAP = {
    "AAA": {"pct_from_open": 5.0, "rvol": 3.0, "rsi14": 80, "above_or_high": True,
            "below_or_low": False, "pct_from_vwap": 1.0, "ema_stack_bull": True,
            "news_sentiment": 0.5, "bars": 50},
    "BBB": {"pct_from_open": -4.0, "rvol": 0.8, "rsi14": 25, "above_or_high": False,
            "below_or_low": True, "pct_from_vwap": -1.0, "ema_stack_bull": False,
            "news_sentiment": -0.4, "bars": 50},
    "CCC": {"pct_from_open": 1.0, "rvol": 2.0, "rsi14": 55, "above_or_high": True,
            "below_or_low": False, "pct_from_vwap": 0.3, "ema_stack_bull": True,
            "news_sentiment": 0.0, "bars": 50},
}


def test_top_gainers_sorted_desc():
    rows = run_scan(SNAP, SCANS_BY_NAME["Top Gainers"])
    assert [r["ticker"] for r in rows] == ["AAA", "CCC", "BBB"]


def test_unusual_volume_filter():
    rows = run_scan(SNAP, SCANS_BY_NAME["Unusual Volume (RVOL>1.5)"])
    tickers = [r["ticker"] for r in rows]
    assert "BBB" not in tickers           # rvol 0.8 filtered out
    assert tickers == ["AAA", "CCC"]      # sorted by rvol desc


def test_oversold_and_overbought():
    os_rows = run_scan(SNAP, SCANS_BY_NAME["Oversold (RSI<35)"])
    assert [r["ticker"] for r in os_rows] == ["BBB"]
    ob_rows = run_scan(SNAP, SCANS_BY_NAME["Overbought (RSI>70)"])
    assert [r["ticker"] for r in ob_rows] == ["AAA"]


def test_news_movers():
    pos = run_scan(SNAP, SCANS_BY_NAME["Positive News Movers"])
    assert [r["ticker"] for r in pos] == ["AAA"]   # CCC rvol ok but sentiment 0.0
    neg = run_scan(SNAP, SCANS_BY_NAME["Negative News Movers"])
    assert neg == [] or all(r["news_sentiment"] < -0.2 for r in neg)


def test_min_bars_excludes_thin():
    snap = {"X": dict(SNAP["AAA"], bars=1)}
    assert run_scan(snap, SCANS_BY_NAME["Top Gainers"]) == []
