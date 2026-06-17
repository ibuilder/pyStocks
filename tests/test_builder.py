"""Tests for user-defined rules & custom scans (storage + scanner merge)."""
from __future__ import annotations

import importlib


def _fresh_storage(tmp_path, monkeypatch):
    from stockpredict import config as cfg
    monkeypatch.setattr(cfg, "DATABASE_URL", f"sqlite:///{(tmp_path/'b.db').as_posix()}")
    import stockpredict.storage as storage
    importlib.reload(storage)
    return storage


def test_rule_enable_disable_delete(tmp_path, monkeypatch):
    storage = _fresh_storage(tmp_path, monkeypatch)
    rid = storage.save_rule("My rule", [{"field": "rsi14", "op": "<", "value": 30}], scope="AAPL")
    assert len(storage.get_rules()) == 1
    storage.set_rule_enabled(rid, False)
    assert storage.get_rules(enabled_only=True) == []
    assert len(storage.get_rules(enabled_only=False)) == 1
    storage.delete_rule(rid)
    assert storage.get_rules(enabled_only=False) == []


def test_custom_scan_crud(tmp_path, monkeypatch):
    storage = _fresh_storage(tmp_path, monkeypatch)
    storage.save_scan("My Movers", [{"field": "rvol", "op": ">", "value": 3}],
                      sort="rvol", desc=True)
    scans = storage.get_scans()
    assert len(scans) == 1 and scans[0]["name"] == "My Movers"
    # upsert by name
    storage.save_scan("My Movers", [{"field": "rvol", "op": ">", "value": 5}], sort="rvol")
    assert storage.get_scans()[0]["filters"][0]["value"] == 5
    storage.delete_scan("My Movers")
    assert storage.get_scans() == []


def test_scanner_service_merges_custom(tmp_path, monkeypatch):
    storage = _fresh_storage(tmp_path, monkeypatch)
    # reload scanners.service so it picks up the reloaded storage module
    import scanners.service as svc
    importlib.reload(svc)
    storage.save_scan("Crazy Volume", [{"field": "rvol", "op": ">", "value": 4}], sort="rvol")
    assert "Crazy Volume" in svc.available()
    snap = {"AAA": {"rvol": 5.0, "bars": 50, "pct_from_open": 1.0},
            "BBB": {"rvol": 1.0, "bars": 50, "pct_from_open": 1.0}}
    rows = svc.run_named("Crazy Volume", snapshot=snap)
    assert [r["ticker"] for r in rows] == ["AAA"]
