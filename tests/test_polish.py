"""Tests for polish helpers: prefs persistence, market status, sort key."""
from __future__ import annotations

import importlib


def test_userprefs_roundtrip(tmp_path, monkeypatch):
    from stockpredict import config as cfg
    monkeypatch.setattr(cfg, "CACHE_DIR", tmp_path)
    import stockpredict.userprefs as up
    importlib.reload(up)
    assert up.load() == {}
    up.save({"geometry": "1000x700", "scan": "Top Gainers"})
    assert up.load()["geometry"] == "1000x700"
    up.update(scan="Oversold (RSI<35)")
    assert up.load()["scan"] == "Oversold (RSI<35)"
    assert up.load()["geometry"] == "1000x700"  # preserved


def test_market_status_shape():
    from stockpredict import market
    label, hint = market.status()
    assert isinstance(label, str) and label
    assert hint in ("green", "amber", "muted")


def test_sort_key_numeric_vs_text():
    from app import _sort_key
    # numbers (group 0) sort before text (group 1)
    assert _sort_key("+3.6%") < _sort_key("+10.0%")
    assert _sort_key("$1,061.25") > _sort_key("$338.68")
    assert _sort_key("███ 70%") > _sort_key("██ 40%")
    assert _sort_key("—")[0] == 1          # non-numeric -> text bucket
    assert _sort_key("▲ +0.50")[1] == 0.50
