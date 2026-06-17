"""Pluggable news feed. yfinance prototype; Benzinga/Polygon are the upgrade.

`get_news(tickers)` -> {ticker: [ {title, summary, publisher, link, published_at} ]}
Cached in-memory with a short TTL so a 1-minute UI poll doesn't hammer the source.
"""
from __future__ import annotations

import os
import time
from datetime import datetime, timezone

PROVIDER = os.environ.get("STOCKPREDICT_NEWS_PROVIDER", "yfinance")
_TTL = 600  # 10 minutes
_cache: dict[str, tuple[float, list[dict]]] = {}


def _parse_yf_item(raw: dict) -> dict | None:
    c = raw.get("content", raw) or {}
    title = c.get("title")
    if not title:
        return None
    pub = c.get("pubDate") or c.get("displayTime")
    try:
        published_at = datetime.fromisoformat(pub.replace("Z", "+00:00")) if pub else None
    except Exception:
        published_at = None
    provider = (c.get("provider") or {}).get("displayName") if isinstance(c.get("provider"), dict) else None
    link = None
    for k in ("canonicalUrl", "clickThroughUrl"):
        v = c.get(k)
        if isinstance(v, dict) and v.get("url"):
            link = v["url"]
            break
    return {
        "title": title,
        "summary": c.get("summary") or c.get("description") or "",
        "publisher": provider,
        "link": link,
        "published_at": published_at,
    }


def _yfinance_news(ticker: str, limit: int) -> list[dict]:
    import yfinance as yf
    try:
        raw = yf.Ticker(ticker).news or []
    except Exception:
        return []
    items = [_parse_yf_item(r) for r in raw]
    items = [i for i in items if i]
    items.sort(key=lambda i: i["published_at"] or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
    return items[:limit]


def get_news(tickers: list[str], limit: int = 8) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    now = time.time()
    for t in tickers:
        hit = _cache.get(t)
        if hit and now - hit[0] < _TTL:
            out[t] = hit[1]
            continue
        items = _yfinance_news(t, limit) if PROVIDER == "yfinance" else []
        _cache[t] = (now, items)
        out[t] = items
    return out
