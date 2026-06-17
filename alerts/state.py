"""Persistence for alert evaluation state (matched flag, last-fired, prev values).

Redis-backed so state survives across Celery task invocations and workers; falls
back to an in-process dict (sufficient for a single long-lived worker or the
standalone ingestor loop) when Redis is unavailable.
"""
from __future__ import annotations

import json

from stockpredict.config import REDIS_URL

_STATE_KEY = "alerts:state"
_mem: dict[str, dict] = {}
_client = None
_tried = False


def _redis():
    global _client, _tried
    if _client is not None:
        return _client
    if _tried:
        return None
    _tried = True
    try:
        import redis
        c = redis.Redis.from_url(REDIS_URL, decode_responses=True, socket_connect_timeout=1)
        c.ping()
        _client = c
        return c
    except Exception:
        return None


def load_all() -> dict[str, dict]:
    c = _redis()
    if not c:
        return dict(_mem)
    try:
        raw = c.hgetall(_STATE_KEY)
        return {k: json.loads(v) for k, v in raw.items()}
    except Exception:
        return dict(_mem)


def save_all(state: dict[str, dict]) -> None:
    global _mem
    _mem = dict(state)
    c = _redis()
    if not c:
        return
    try:
        pipe = c.pipeline()
        pipe.delete(_STATE_KEY)
        if state:
            pipe.hset(_STATE_KEY, mapping={k: json.dumps(v) for k, v in state.items()})
        pipe.execute()
    except Exception:
        pass
