"""Configuration and the default universe.

Everything here is plain data so it's easy to tune. The universe ships as a
curated list of large, liquid U.S. names so the app works out of the box with no
API key; you can switch to the full S&P 500 (scraped from Wikipedia) from the UI.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

try:  # optional: load a local .env if python-dotenv is installed
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

# Where we cache downloaded data, the SQLite DB, prefs, logs, and reports.
# In a packaged (frozen) build the exe dir may be read-only, so always use a
# per-user writable location: %LOCALAPPDATA%\stockpredict on Windows.
def _default_cache_dir() -> Path:
    env = os.environ.get("STOCKPREDICT_CACHE")
    if env:
        return Path(env)
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA")
        if base:
            return Path(base) / "stockpredict"
    return Path.home() / ".stockpredict_cache"


CACHE_DIR = _default_cache_dir()
CACHE_DIR.mkdir(parents=True, exist_ok=True)

# --- Phase 0 infrastructure -------------------------------------------------
# Broker/result backend for Celery (Redis). Override via env for prod.
REDIS_URL = os.environ.get("STOCKPREDICT_REDIS_URL", "redis://localhost:6379/0")

# Durable storage. Defaults to a zero-setup SQLite file so the app runs out of
# the box; point at Postgres/TimescaleDB in prod, e.g.
#   STOCKPREDICT_DATABASE_URL=postgresql+psycopg2://user:pass@host:5432/stockpredict
DATABASE_URL = os.environ.get(
    "STOCKPREDICT_DATABASE_URL",
    f"sqlite:///{(CACHE_DIR / 'stockpredict.db').as_posix()}",
)

# Horizons we estimate for. Keys are used throughout the code & UI.
HORIZONS = {
    "week": {"label": "Next Week", "trading_days": 5},
    "month": {"label": "Next Month", "trading_days": 21},
    "year": {"label": "Next Year", "trading_days": 252},
}

# How often the background aggregator refreshes prices, in seconds.
DEFAULT_REFRESH_SECONDS = 15 * 60  # 15 minutes — be polite to the data feed.

# Fundamentals are slow to fetch (one call each), so we refresh them less often
# and rotate through the universe a chunk at a time.
FUNDAMENTALS_TTL_SECONDS = 12 * 60 * 60  # 12 hours
FUNDAMENTALS_CHUNK = 25

# How many price-history days to pull (need ~1yr + buffer for 12-1 momentum).
HISTORY_DAYS = 400


# A curated, liquid default universe across sectors. Works with zero setup.
DEFAULT_WATCHLIST = [
    # Mega-cap tech
    "AAPL", "MSFT", "GOOGL", "AMZN", "META", "NVDA", "AVGO", "ORCL", "ADBE", "CRM",
    "AMD", "INTC", "QCOM", "TXN", "CSCO", "IBM", "NOW", "INTU", "AMAT", "MU",
    # Consumer / retail
    "WMT", "COST", "HD", "LOW", "NKE", "MCD", "SBUX", "TGT", "PG", "KO",
    "PEP", "DIS", "NFLX", "TSLA", "BKNG", "CMG",
    # Financials
    "JPM", "BAC", "WFC", "GS", "MS", "C", "AXP", "BLK", "SCHW", "V", "MA", "PYPL",
    # Healthcare
    "UNH", "JNJ", "LLY", "PFE", "MRK", "ABBV", "TMO", "ABT", "DHR", "BMY", "AMGN",
    # Industrials / energy / materials
    "CAT", "BA", "GE", "HON", "UPS", "RTX", "LMT", "DE", "XOM", "CVX", "COP",
    "LIN", "FCX", "NEE",
    # Communication / misc
    "T", "VZ", "CMCSA", "TMUS",
]


@dataclass
class Config:
    universe_source: str = "watchlist"  # "watchlist" | "sp500"
    watchlist: list[str] = field(default_factory=lambda: list(DEFAULT_WATCHLIST))
    top_n: int = 25
    refresh_seconds: int = DEFAULT_REFRESH_SECONDS


config = Config()
