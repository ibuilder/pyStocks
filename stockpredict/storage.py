"""Durable storage for signal snapshots (SQLAlchemy).

Defaults to a zero-setup SQLite file so everything runs immediately; swap to
Postgres/TimescaleDB in production by setting STOCKPREDICT_DATABASE_URL. The rest
of the app only talks to the small functional API at the bottom, so the backend is
an implementation detail.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pandas as pd
from sqlalchemy import (
    Boolean, Column, DateTime, Float, Integer, String, Text, create_engine, select, func,
)
from sqlalchemy.orm import declarative_base, sessionmaker

from .config import DATABASE_URL

Base = declarative_base()


class SignalRow(Base):
    __tablename__ = "signal_rows"

    id = Column(Integer, primary_key=True, autoincrement=True)
    run_id = Column(String(36), index=True, nullable=False)
    created_at = Column(DateTime, index=True, nullable=False)
    horizon = Column(String(8), index=True, nullable=False)   # week|month|year
    rank = Column(Integer, nullable=False)
    ticker = Column(String(12), index=True, nullable=False)
    est_return = Column(Float)
    band_lo = Column(Float)
    band_hi = Column(Float)
    confidence = Column(Float)
    signal_z = Column(Float)
    price = Column(Float)
    universe_source = Column(String(16))
    reasons = Column(String(512))


class BacktestMetric(Base):
    __tablename__ = "backtest_metrics"

    id = Column(Integer, primary_key=True, autoincrement=True)
    run_id = Column(String(36), index=True, nullable=False)
    created_at = Column(DateTime, index=True, nullable=False)
    horizon = Column(String(8), index=True, nullable=False)
    periods = Column(Integer)
    strat_cagr = Column(Float)
    bench_cagr = Column(Float)
    excess_cagr = Column(Float)
    strat_sharpe = Column(Float)
    max_drawdown = Column(Float)
    hit_rate = Column(Float)
    ic_mean = Column(Float)
    ic_t_stat = Column(Float)


class AlertRule(Base):
    __tablename__ = "alert_rules"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(120), nullable=False)
    scope = Column(String(12), default="*")        # "*" = whole watchlist, or a ticker
    conditions = Column(Text, nullable=False)       # JSON list of {field, op, value}
    cooldown_sec = Column(Integer, default=1800)
    enabled = Column(Boolean, default=True)
    created_at = Column(DateTime)


class CustomScan(Base):
    __tablename__ = "custom_scans"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(120), unique=True, nullable=False)
    filters = Column(Text, nullable=False)      # JSON list of {field, op, value}
    sort = Column(String(40))
    desc = Column(Boolean, default=True)
    created_at = Column(DateTime)


class AlertFired(Base):
    __tablename__ = "alerts_fired"

    id = Column(Integer, primary_key=True, autoincrement=True)
    fired_at = Column(DateTime, index=True, nullable=False)
    rule_id = Column(Integer, index=True)
    rule_name = Column(String(120))
    ticker = Column(String(12), index=True)
    message = Column(String(400))


_engine = None
_Session = None


def _ensure_engine():
    global _engine, _Session
    if _engine is None:
        # check_same_thread off so the aggregator thread + UI can share SQLite.
        connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
        _engine = create_engine(DATABASE_URL, future=True, connect_args=connect_args)
        Base.metadata.create_all(_engine)
        _Session = sessionmaker(bind=_engine, future=True)
    return _engine


def init_db():
    """Create tables if needed (idempotent)."""
    _ensure_engine()


# --------------------------------------------------------------- write API ---
def save_snapshot(results: dict[str, pd.DataFrame], universe_source: str = "watchlist") -> str:
    """Persist one full run (all horizons). Returns the run_id."""
    _ensure_engine()
    run_id = uuid.uuid4().hex
    now = datetime.now(timezone.utc)
    rows: list[SignalRow] = []
    for horizon, df in (results or {}).items():
        if df is None or df.empty:
            continue
        for _, r in df.iterrows():
            rows.append(SignalRow(
                run_id=run_id,
                created_at=now,
                horizon=horizon,
                rank=int(r.get("rank", r.name) if "rank" in r else r.name),
                ticker=str(r["ticker"]),
                est_return=_num(r.get("est_return")),
                band_lo=_num(r.get("band_lo")),
                band_hi=_num(r.get("band_hi")),
                confidence=_num(r.get("confidence")),
                signal_z=_num(r.get("signal_z")),
                price=_num(r.get("price")),
                universe_source=universe_source,
                reasons=str(r.get("reasons", ""))[:512],
            ))
    if not rows:
        return run_id
    with _Session() as s:
        s.add_all(rows)
        s.commit()
    return run_id


# ---------------------------------------------------------------- read API ---
def latest_run_id() -> str | None:
    _ensure_engine()
    with _Session() as s:
        row = s.execute(
            select(SignalRow.run_id)
            .order_by(SignalRow.created_at.desc())
            .limit(1)
        ).first()
        return row[0] if row else None


def load_latest() -> dict[str, pd.DataFrame]:
    """Return {horizon: DataFrame} for the most recent run (for the UI)."""
    rid = latest_run_id()
    if not rid:
        return {}
    return load_run(rid)


def load_run(run_id: str) -> dict[str, pd.DataFrame]:
    _ensure_engine()
    with _Session() as s:
        rows = s.execute(
            select(SignalRow).where(SignalRow.run_id == run_id)
            .order_by(SignalRow.horizon, SignalRow.rank)
        ).scalars().all()
    out: dict[str, pd.DataFrame] = {}
    for r in rows:
        out.setdefault(r.horizon, []).append({
            "rank": r.rank, "ticker": r.ticker, "est_return": r.est_return,
            "band_lo": r.band_lo, "band_hi": r.band_hi, "confidence": r.confidence,
            "signal_z": r.signal_z, "price": r.price, "reasons": r.reasons,
        })
    return {h: pd.DataFrame(v).set_index("rank", drop=False) for h, v in out.items()}


def save_backtest_metrics(metrics_by_horizon: dict[str, dict]) -> str:
    """Persist one backtest run's metrics (one row per horizon). Returns run_id."""
    _ensure_engine()
    run_id = uuid.uuid4().hex
    now = datetime.now(timezone.utc)
    rows = []
    for horizon, m in (metrics_by_horizon or {}).items():
        rows.append(BacktestMetric(
            run_id=run_id, created_at=now, horizon=horizon,
            periods=int(m.get("periods") or 0),
            strat_cagr=_num(m.get("strat_cagr")), bench_cagr=_num(m.get("bench_cagr")),
            excess_cagr=_num(m.get("excess_cagr")), strat_sharpe=_num(m.get("strat_sharpe")),
            max_drawdown=_num(m.get("max_drawdown")), hit_rate=_num(m.get("hit_rate")),
            ic_mean=_num(m.get("ic_mean")), ic_t_stat=_num(m.get("ic_t_stat")),
        ))
    if rows:
        with _Session() as s:
            s.add_all(rows)
            s.commit()
    return run_id


def run_count() -> int:
    _ensure_engine()
    with _Session() as s:
        return int(s.execute(select(func.count(func.distinct(SignalRow.run_id)))).scalar() or 0)


# --------------------------------------------------------------- alerts API ---
import json as _json  # noqa: E402

DEFAULT_ALERT_RULES = [
    {"name": "Oversold + above VWAP (bounce setup)", "scope": "*", "cooldown_sec": 1800,
     "conditions": [{"field": "rsi14", "op": "<", "value": 32},
                    {"field": "pct_from_vwap", "op": ">", "value": 0}]},
    {"name": "High-RVOL opening-range breakout", "scope": "*", "cooldown_sec": 1800,
     "conditions": [{"field": "rvol", "op": ">", "value": 2.0},
                    {"field": "above_or_high", "op": "is_true", "value": True}]},
    {"name": "Breakdown below opening range", "scope": "*", "cooldown_sec": 1800,
     "conditions": [{"field": "below_or_low", "op": "is_true", "value": True},
                    {"field": "rvol", "op": ">", "value": 1.5}]},
    {"name": "Strong intraday trend (+3% & EMA stack)", "scope": "*", "cooldown_sec": 1800,
     "conditions": [{"field": "pct_from_open", "op": ">", "value": 3.0},
                    {"field": "ema_stack_bull", "op": "is_true", "value": True}]},
    {"name": "Overbought (RSI > 75)", "scope": "*", "cooldown_sec": 1800,
     "conditions": [{"field": "rsi14", "op": ">", "value": 75}]},
    {"name": "Positive news + volume", "scope": "*", "cooldown_sec": 3600,
     "conditions": [{"field": "news_sentiment", "op": ">", "value": 0.3},
                    {"field": "rvol", "op": ">", "value": 1.5}]},
    {"name": "Negative news + volume", "scope": "*", "cooldown_sec": 3600,
     "conditions": [{"field": "news_sentiment", "op": "<", "value": -0.3},
                    {"field": "rvol", "op": ">", "value": 1.5}]},
]


def get_rules(enabled_only: bool = True) -> list[dict]:
    _ensure_engine()
    with _Session() as s:
        q = select(AlertRule)
        if enabled_only:
            q = q.where(AlertRule.enabled == True)  # noqa: E712
        rows = s.execute(q.order_by(AlertRule.id)).scalars().all()
    return [{"id": r.id, "name": r.name, "scope": r.scope,
             "conditions": _json.loads(r.conditions), "cooldown_sec": r.cooldown_sec,
             "enabled": r.enabled} for r in rows]


def save_rule(name: str, conditions: list[dict], scope: str = "*",
              cooldown_sec: int = 1800, enabled: bool = True) -> int:
    _ensure_engine()
    with _Session() as s:
        rule = AlertRule(name=name, scope=scope, conditions=_json.dumps(conditions),
                         cooldown_sec=cooldown_sec, enabled=enabled,
                         created_at=datetime.now(timezone.utc))
        s.add(rule)
        s.commit()
        return rule.id


def seed_default_rules() -> int:
    """Insert the built-in starter rules if no rules exist. Returns count added."""
    _ensure_engine()
    if get_rules(enabled_only=False):
        return 0
    for r in DEFAULT_ALERT_RULES:
        save_rule(r["name"], r["conditions"], r["scope"], r["cooldown_sec"])
    return len(DEFAULT_ALERT_RULES)


def set_rule_enabled(rule_id: int, enabled: bool) -> None:
    _ensure_engine()
    with _Session() as s:
        rule = s.get(AlertRule, rule_id)
        if rule:
            rule.enabled = enabled
            s.commit()


def delete_rule(rule_id: int) -> None:
    _ensure_engine()
    with _Session() as s:
        rule = s.get(AlertRule, rule_id)
        if rule:
            s.delete(rule)
            s.commit()


# ---- custom scans (user-defined, merged with the built-in library) ----------
def save_scan(name: str, filters: list[dict], sort: str = "pct_from_open", desc: bool = True) -> int:
    _ensure_engine()
    with _Session() as s:
        existing = s.execute(select(CustomScan).where(CustomScan.name == name)).scalar_one_or_none()
        if existing:
            existing.filters = _json.dumps(filters)
            existing.sort = sort
            existing.desc = desc
            s.commit()
            return existing.id
        scan = CustomScan(name=name, filters=_json.dumps(filters), sort=sort, desc=desc,
                          created_at=datetime.now(timezone.utc))
        s.add(scan)
        s.commit()
        return scan.id


def get_scans() -> list[dict]:
    _ensure_engine()
    with _Session() as s:
        rows = s.execute(select(CustomScan).order_by(CustomScan.id)).scalars().all()
    return [{"name": r.name, "filters": _json.loads(r.filters), "sort": r.sort,
             "desc": r.desc, "custom": True} for r in rows]


def delete_scan(name: str) -> None:
    _ensure_engine()
    with _Session() as s:
        row = s.execute(select(CustomScan).where(CustomScan.name == name)).scalar_one_or_none()
        if row:
            s.delete(row)
            s.commit()


def save_fired(rule_id: int, rule_name: str, ticker: str, message: str) -> None:
    _ensure_engine()
    with _Session() as s:
        s.add(AlertFired(fired_at=datetime.now(timezone.utc), rule_id=rule_id,
                         rule_name=rule_name, ticker=ticker, message=message[:400]))
        s.commit()


def recent_fired(limit: int = 100) -> list[dict]:
    _ensure_engine()
    with _Session() as s:
        rows = s.execute(
            select(AlertFired).order_by(AlertFired.fired_at.desc()).limit(limit)
        ).scalars().all()
    return [{"fired_at": r.fired_at, "rule_name": r.rule_name,
             "ticker": r.ticker, "message": r.message} for r in rows]


def _num(x):
    try:
        if x is None:
            return None
        x = float(x)
        return None if x != x else x  # drop NaN
    except (TypeError, ValueError):
        return None
