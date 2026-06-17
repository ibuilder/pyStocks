"""Alert engine tests — pure evaluate(), edge-triggering, crosses, cooldown."""
from __future__ import annotations

from alerts.engine import evaluate, _check


RULE = {"id": 1, "name": "Oversold+VWAP", "scope": "*", "cooldown_sec": 600,
        "conditions": [{"field": "rsi14", "op": "<", "value": 32},
                       {"field": "pct_from_vwap", "op": ">", "value": 0}]}


def test_check_ops():
    ind = {"rsi14": 28.0, "above_or_high": True, "pct_from_vwap": 0.5}
    assert _check({"field": "rsi14", "op": "<", "value": 32}, ind, {})
    assert not _check({"field": "rsi14", "op": ">", "value": 32}, ind, {})
    assert _check({"field": "above_or_high", "op": "is_true", "value": True}, ind, {})
    assert not _check({"field": "above_or_high", "op": "is_false", "value": True}, ind, {})
    # None values never match numeric ops
    assert not _check({"field": "vwap", "op": ">", "value": 1}, {"vwap": None}, {})


def test_crosses_above_needs_transition():
    cond = {"field": "pct_from_vwap", "op": "crosses_above", "value": 0}
    assert _check(cond, {"pct_from_vwap": 0.2}, {"pct_from_vwap": -0.3})   # crossed up
    assert not _check(cond, {"pct_from_vwap": 0.4}, {"pct_from_vwap": 0.2})  # already above
    assert not _check(cond, {"pct_from_vwap": 0.2}, {})                      # no prior value


def test_edge_trigger_and_cooldown():
    snap = {"AAA": {"rsi14": 28, "pct_from_vwap": 0.5, "last": 10.0, "pct_from_open": -1.0}}
    state = {}
    fired, state = evaluate(snap, [RULE], state, now=1000.0)
    assert len(fired) == 1 and fired[0]["ticker"] == "AAA"

    # still matching, within cooldown -> no re-fire
    fired, state = evaluate(snap, [RULE], state, now=1100.0)
    assert fired == []

    # condition stops matching, then matches again -> fires (edge)
    snap2 = {"AAA": {"rsi14": 40, "pct_from_vwap": 0.5, "last": 10.0, "pct_from_open": 0.0}}
    fired, state = evaluate(snap2, [RULE], state, now=1200.0)
    assert fired == []
    fired, state = evaluate(snap, [RULE], state, now=1300.0)
    assert len(fired) == 1

    # after cooldown elapses while continuously matching -> re-fires
    state = {"1|AAA": {"matched": True, "last_fired": 1300.0,
                       "vals": {"rsi14": 28, "pct_from_vwap": 0.5}}}
    fired, _ = evaluate(snap, [RULE], state, now=1300.0 + 601)
    assert len(fired) == 1


def test_scope_specific_ticker():
    rule = dict(RULE, scope="MSFT")
    snap = {"AAA": {"rsi14": 10, "pct_from_vwap": 1}, "MSFT": {"rsi14": 10, "pct_from_vwap": 1}}
    fired, _ = evaluate(snap, [rule], {}, now=1.0)
    assert {a["ticker"] for a in fired} == {"MSFT"}
