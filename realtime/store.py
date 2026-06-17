"""Redis-backed store for the latest intraday indicator snapshot.

Writes both a per-ticker hash (fast "latest" lookup for the UI) and appends to a
Redis Stream (durable, replayable history — the Phase 2 architecture). Degrades
gracefully: if Redis is unreachable, reads/writes become no-ops and callers fall
back to computing on demand.
"""
from __future__ import annotations

import json
import time

from stockpredict.config import REDIS_URL

_SNAPSHOT_KEY = "intraday:latest"     # hash: ticker -> json(indicators)
_STREAM_KEY = "intraday:stream"       # stream of indicator events
_META_KEY = "intraday:meta"           # hash: updated_at, count

_client = None
_unavailable_until = 0.0


def _redis():
    """Return a cached Redis client, or None if unreachable (with backoff)."""
    global _client, _unavailable_until
    if _client is not None:
        return _client
    if time.time() < _unavailable_until:
        return None
    try:
        import redis
        c = redis.Redis.from_url(REDIS_URL, decode_responses=True, socket_connect_timeout=1)
        c.ping()
        _client = c
        return c
    except Exception:
        _unavailable_until = time.time() + 30  # back off before retrying
        return None


def publish(snapshot: dict[str, dict]) -> bool:
    """Store the latest indicators for many tickers. Returns True if persisted."""
    c = _redis()
    if not c:
        return False
    now = time.time()
    try:
        pipe = c.pipeline()
        for ticker, ind in snapshot.items():
            payload = json.dumps(ind)
            pipe.hset(_SNAPSHOT_KEY, ticker, payload)
            pipe.xadd(_STREAM_KEY, {"ticker": ticker, "data": payload},
                      maxlen=10000, approximate=True)
        pipe.hset(_META_KEY, mapping={"updated_at": now, "count": len(snapshot)})
        pipe.execute()
        return True
    except Exception:
        return False


def load_latest() -> dict[str, dict]:
    c = _redis()
    if not c:
        return {}
    try:
        raw = c.hgetall(_SNAPSHOT_KEY)
        return {t: json.loads(v) for t, v in raw.items()}
    except Exception:
        return {}


def meta() -> dict:
    c = _redis()
    if not c:
        return {}
    try:
        m = c.hgetall(_META_KEY)
        if "updated_at" in m:
            m["updated_at"] = float(m["updated_at"])
        if "count" in m:
            m["count"] = int(m["count"])
        return m
    except Exception:
        return {}
