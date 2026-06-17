"""News service: fetch headlines, score sentiment, publish per-ticker aggregate.

Publishes to Redis (`news:latest` hash) so the intraday ingestor can merge a
`news_sentiment` field into each ticker's snapshot (making it alertable) and the
window can show headlines. Degrades gracefully without Redis.
"""
from __future__ import annotations

import json
import time

from stockpredict.config import REDIS_URL, DEFAULT_WATCHLIST
from .feed import get_news
from .sentiment import score_headlines, score_text

_LATEST_KEY = "news:latest"     # hash: ticker -> json(aggregate)
_HEADLINES_KEY = "news:headlines"  # hash: ticker -> json(list of scored headlines)
_client = None
_tried = False
_mem: dict[str, dict] = {}
_mem_headlines: dict[str, list] = {}


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


def refresh_news(tickers: list[str] | None = None, limit: int = 8, progress=None) -> dict[str, dict]:
    tickers = tickers or list(DEFAULT_WATCHLIST)
    if progress:
        progress(f"Fetching news for {len(tickers)} tickers…")
    news = get_news(tickers, limit=limit)

    agg: dict[str, dict] = {}
    headlines: dict[str, list] = {}
    for t, items in news.items():
        if not items:
            continue
        agg[t] = score_headlines(items)
        headlines[t] = [{
            "title": it.get("title"),
            "publisher": it.get("publisher"),
            "link": it.get("link"),
            "published_at": it["published_at"].isoformat() if it.get("published_at") else None,
            "score": score_text((it.get("title") or "") + ". " + (it.get("summary") or ""))["score"],
        } for it in items]

    _publish(agg, headlines)
    if progress:
        progress(f"Scored news for {len(agg)} tickers.")
    return agg


def _publish(agg: dict[str, dict], headlines: dict[str, list]):
    global _mem, _mem_headlines
    _mem, _mem_headlines = agg, headlines
    c = _redis()
    if not c:
        return
    try:
        pipe = c.pipeline()
        if agg:
            pipe.hset(_LATEST_KEY, mapping={t: json.dumps(v) for t, v in agg.items()})
        if headlines:
            pipe.hset(_HEADLINES_KEY, mapping={t: json.dumps(v) for t, v in headlines.items()})
        pipe.execute()
    except Exception:
        pass


def load_latest() -> dict[str, dict]:
    c = _redis()
    if not c:
        return dict(_mem)
    try:
        raw = c.hgetall(_LATEST_KEY)
        return {t: json.loads(v) for t, v in raw.items()} or dict(_mem)
    except Exception:
        return dict(_mem)


def load_headlines() -> dict[str, list]:
    c = _redis()
    if not c:
        return dict(_mem_headlines)
    try:
        raw = c.hgetall(_HEADLINES_KEY)
        return {t: json.loads(v) for t, v in raw.items()} or dict(_mem_headlines)
    except Exception:
        return dict(_mem_headlines)
