"""Pure alert evaluation logic (no I/O — trivially testable).

A rule is {id, name, scope, conditions, cooldown_sec}. Each condition is
{field, op, value}; all conditions in a rule are AND-combined. Supported ops:

    >  <  >=  <=  ==  !=        numeric / equality
    is_true  is_false          boolean indicator flags
    crosses_above  crosses_below   transition vs the previous snapshot value

State (per rule+ticker) carries the previous matched flag, last-fired timestamp,
and the previous field values needed for crosses. `evaluate` returns the list of
freshly-fired alerts plus the next state.
"""
from __future__ import annotations

NUMERIC_OPS = {
    ">": lambda c, v, p: c > v,
    "<": lambda c, v, p: c < v,
    ">=": lambda c, v, p: c >= v,
    "<=": lambda c, v, p: c <= v,
    "==": lambda c, v, p: c == v,
    "!=": lambda c, v, p: c != v,
    "crosses_above": lambda c, v, p: p is not None and p < v <= c,
    "crosses_below": lambda c, v, p: p is not None and p > v >= c,
}
BOOL_OPS = {"is_true", "is_false"}

# Exposed for the UI rule/scan builders.
SUPPORTED_OPS = ["<", "<=", ">", ">=", "==", "!=", "crosses_above", "crosses_below",
                 "is_true", "is_false"]

# Indicator fields a rule/scan can reference, with (label, kind).
SUPPORTED_FIELDS = [
    ("pct_from_open", "% from open", "num"),
    ("pct_from_vwap", "% from VWAP", "num"),
    ("rvol", "Relative volume", "num"),
    ("rsi14", "RSI(14)", "num"),
    ("atr14", "ATR(14)", "num"),
    ("last", "Last price", "num"),
    ("news_sentiment", "News sentiment", "num"),
    ("news_count", "News count", "num"),
    ("above_or_high", "Above opening-range high", "bool"),
    ("below_or_low", "Below opening-range low", "bool"),
    ("above_ema9", "Above EMA9", "bool"),
    ("ema_stack_bull", "EMA stack bullish", "bool"),
]
FIELD_LABELS = {f: lbl for f, lbl, _ in SUPPORTED_FIELDS}


def _check(cond: dict, ind: dict, prev_vals: dict) -> bool:
    field, op = cond["field"], cond["op"]
    cur = ind.get(field)
    if op in BOOL_OPS:
        return (cur is True) if op == "is_true" else (cur is False)
    if cur is None:
        return False
    try:
        cur = float(cur)
    except (TypeError, ValueError):
        return False
    prev = prev_vals.get(field)
    try:
        prev = float(prev) if prev is not None else None
    except (TypeError, ValueError):
        prev = None
    fn = NUMERIC_OPS.get(op)
    return bool(fn(cur, cond["value"], prev)) if fn else False


def _message(rule: dict, ticker: str, ind: dict) -> str:
    parts = []
    for c in rule["conditions"]:
        val = ind.get(c["field"])
        if isinstance(val, float):
            val = round(val, 2)
        parts.append(f"{c['field']}={val}")
    extra = []
    if ind.get("last") is not None:
        extra.append(f"${ind['last']:,.2f}")
    if ind.get("pct_from_open") is not None:
        extra.append(f"{ind['pct_from_open']:+.1f}% open")
    head = f"{ticker}: {rule['name']}"
    return f"{head} — {', '.join(parts)}" + (f"  ({', '.join(extra)})" if extra else "")


def evaluate(snapshot: dict[str, dict], rules: list[dict], state: dict[str, dict],
             now: float) -> tuple[list[dict], dict[str, dict]]:
    """Return (fired_alerts, new_state).

    fired_alerts: list of {rule_id, rule_name, ticker, message}.
    """
    fired: list[dict] = []
    new_state = dict(state)

    for rule in rules:
        scope = rule.get("scope", "*")
        tickers = list(snapshot) if scope == "*" else ([scope] if scope in snapshot else [])
        cooldown = rule.get("cooldown_sec", 1800)
        for ticker in tickers:
            ind = snapshot.get(ticker) or {}
            key = f"{rule['id']}|{ticker}"
            st = state.get(key, {})
            prev_vals = st.get("vals", {})

            matched = all(_check(c, ind, prev_vals) for c in rule["conditions"])
            new_vals = {c["field"]: ind.get(c["field"]) for c in rule["conditions"]}

            do_fire = False
            if matched:
                was = st.get("matched", False)
                last_fired = st.get("last_fired", 0.0)
                if (not was) or (now - last_fired >= cooldown):
                    do_fire = True

            new_state[key] = {
                "matched": matched,
                "last_fired": now if do_fire else st.get("last_fired", 0.0),
                "vals": new_vals,
            }
            if do_fire:
                fired.append({
                    "rule_id": rule["id"], "rule_name": rule["name"],
                    "ticker": ticker, "message": _message(rule, ticker, ind),
                })
    return fired, new_state
