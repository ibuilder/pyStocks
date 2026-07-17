# stockpredict — day-trading research companion

A Python desktop application that turns continuously-aggregated market data into a
single research surface for a discretionary trader: **multi-horizon return
estimates** (week / month / year), **live intraday technicals**, **news +
sentiment**, **market-wide scanners**, and a **rule-based alert engine** with
desktop notifications — all fed by a Celery + Redis background pipeline and
validated by a point-in-time backtesting harness.

> **Read this first.** This is a *research / decision-support companion*, **not** a
> prediction engine, **not** an auto-trader, and **not** investment advice. No
> public tool reliably forecasts stock returns. Day trading is, per the academic
> record, a net-losing activity for most retail participants. The value here is
> *speed, situational awareness, and discipline* — every number is an estimate with
> wide error bars. The app never places trades; it surfaces information for you.

📄 **Project landing page:** [`index.html`](index.html) (GitHub Pages-ready).
🗺️ **Roadmap & phase status:** [`ROADMAP.md`](ROADMAP.md).

---

## Run it

```powershell
# from C:\Server\pystocks
pip install -r requirements.txt      # one-time
python app.py
```

> **Standalone .exe (no Python needed):** `pyinstaller stockpredict.spec` →
> `dist\stockpredict.exe`. The GUI runs fully in-process, so the exe needs no
> Redis/Celery. Full build/signing/installer notes in [PACKAGING.md](PACKAGING.md).

A window opens, immediately starts pulling data, and populates seven tabs:
**Next Week · Next Month · Next Year · ⚡ Intraday · 🔔 Alerts · 📰 News · 🔍 Scanners**.
It auto-refreshes on a schedule (default 15 min) and has a **Refresh now** button.
Double-click any return-estimate row for a factor-by-factor breakdown.

**Desktop UX niceties:**
- Click any column header to **sort** (numeric-aware, persists across live refreshes).
- **Quick filter box** — type a ticker fragment to filter every tab instantly.
- **Export CSV** — one click exports the active tab's table.
- **Price sparkline** — double-click a return-estimate row for a factor breakdown
  *and* a 120-session price chart (drawn from the local cache, no network).
- **Embedded intraday chart** — select a row on the Intraday tab to see its
  intraday price line with a **VWAP overlay** in a panel below the table.
- **Right-click any row** → Copy ticker · Open in Yahoo Finance · New alert.
- **Sound on alert** — optional beep when a new alert fires (toggle on the Alerts tab).
- Header **market-session indicator** (open / pre-market / after-hours / closed)
  with a **next-refresh countdown**.
- **Friendly empty/loading states** everywhere.
- **Persisted preferences** — universe, refresh interval, auto-refresh, selected
  scan, filter, **column widths**, sound toggle and window size restored on next
  launch (`~/.stockpredict_cache/prefs.json`).

### Project structure
```
app.py                     Tkinter desktop window (7 tabs, builders, toasts)
stockpredict/              core: data, factors, model, screen pipeline, storage,
                           Celery app + scheduled tasks
realtime/                  intraday feed -> indicators -> Redis snapshot/stream
news/                      headline feed + finance-lexicon sentiment
alerts/                    pure rule engine + state + delivery wiring
scanners/                  market-wide filtered/ranked views (built-in + custom)
notify/                    pluggable notification channels (desktop toast, log)
backtest/                  point-in-time harness, tearsheet report, CLI
tests/                     28 offline tests (pytest -q)
docker-compose.yml         Redis (TimescaleDB ready); index.html  GitHub Pages
```

The desktop app now loads the **last saved run instantly** on startup (including
runs produced by the background Celery pipeline below), then refreshes live.

- **Universe:** *Curated (70)* liquid large-caps (default, no key) or *S&P 500*
  (scraped from Wikipedia at runtime).
- **Data:** [yfinance](https://github.com/ranaroussi/yfinance) — an unofficial
  Yahoo feed, fine for a prototype, not for production. Swap in a licensed
  provider in `stockpredict/data.py`.

---

## Background pipeline (Phase 0 — Celery + Redis)

The screen also runs as a scheduled background job, so the most recent research is
ready before you open the window. Same code path as the desktop app
(`pipeline.run_screen`), results persisted to a database (SQLite by default,
Postgres-ready).

```powershell
pip install -r requirements.txt

# 1) Broker (Redis) via Docker
docker compose up -d redis

# 2) Worker (use --pool=solo on Windows) and the scheduler
celery -A stockpredict.celery_app worker --loglevel=info --pool=solo
celery -A stockpredict.celery_app beat   --loglevel=info

# Trigger a run on demand instead of waiting for the schedule:
python -c "from stockpredict.tasks import run_daily_screen; print(run_daily_screen.delay().get(timeout=120))"

# Or run the whole pipeline inline with no broker (dev/smoke):
python -m stockpredict.tasks
```

**Schedule** (`celery_app.py`, America/New_York): a full **pre-market screen at
7:30 AM ET** weekdays, plus a **light intraday refresh every 30 min** during the
cash session. Both persist a snapshot the desktop app picks up on next launch.

**Config** (via `.env`, see `.env.example`):
- `STOCKPREDICT_REDIS_URL` — broker/result backend (default `redis://localhost:6379/0`).
- `STOCKPREDICT_DATABASE_URL` — durable store; unset = SQLite. For prod, set a
  Postgres/TimescaleDB URL and uncomment the `db` service in `docker-compose.yml`.

**Tests:** `pytest -q` (offline — yfinance is stubbed).

This is **Phase 0** of [ROADMAP.md](ROADMAP.md): the foundation the real-time
streaming spine, scanners, news/sentiment, and backtesting build on. The next data
upgrade is a licensed real-time provider (Alpaca for free real-time + paper
trading; Polygon/Databento for low latency) — wired in `stockpredict/data.py`.

---

## Backtesting & validation (Phase 1)

No signal is trusted as "actionable" until it survives an out-of-sample backtest.
The harness ranks the universe by each horizon's **price** signal point-in-time
(no lookahead), buys the top-N equal-weight, holds for the horizon, and compares to
an equal-weight-universe benchmark.

```powershell
python -m backtest.run                       # all horizons, 10y history
python -m backtest.run --horizon month --walk-forward --open
python -m backtest.run --sp500 --top-n 15 --cost-bps 8
```

Produces a self-contained **HTML tearsheet** (equity curves, metrics, caveats) in
`~/.stockpredict_cache/reports/`. The weekly Celery job
`run_weekly_backtest` (Beat: Sun 06:00 ET) re-runs it and stores metrics in the
`backtest_metrics` table.

**The metric that matters** for a ranking model is the **Information Coefficient
(IC)** — rank correlation between predicted score and realized forward return. An
IC t-stat above ~2 is the bar for "the signal is real."

**Honest findings on the current default universe (10y):**

| Horizon | Excess CAGR vs benchmark | IC (t-stat) | Verdict |
|---|---|---|---|
| Week | −2.5% | −0.00 (−0.2) | **No edge** — weekly reversal doesn't survive costs here |
| Month | +10.1% | +0.03 (1.3) | **Most promising**, not yet conclusive |
| Year | +5.7% | +0.04 (0.4) | Too few samples (8) to trust |

**Deliberate limitations (flagged in every tearsheet):**
- **Fundamentals excluded.** yfinance gives only a *current* snapshot; backtesting
  quality/value would leak the future. Needs point-in-time fundamentals (a data-lake
  upgrade) before those factors can be validated.
- **Survivorship bias.** The universe is *today's* constituents.
- **Few year-horizon samples** with non-overlapping windows over 10y.

`--walk-forward` additionally fits **evidence-based weights** (∝ each factor's
in-sample IC) on the first 60% of history and reports their out-of-sample
performance vs the current hand-set weights — the data-driven re-fit, not a curve-fit.

---

## Real-time intraday spine (Phase 2, Increment 1)

The first piece of the day-trading companion: Celery refreshes **live intraday
research** every minute during market hours, publishes it to Redis, and the desktop
window shows it on the **⚡ Intraday** tab.

```powershell
# Standalone dev loop (no Celery needed) — polls every 60s:
python -m realtime.ingestor

# Or via Celery (Beat schedule: every minute, 9:00–16:59 ET, Mon–Fri):
celery -A stockpredict.celery_app worker --loglevel=info --pool=solo
celery -A stockpredict.celery_app beat   --loglevel=info
```

**Per-ticker indicators** (`realtime/indicators.py`): last, % from open, VWAP &
distance from it, day high/low, **opening-range break**, **relative volume (RVOL)**,
**RSI(14)**, **ATR(14)**, **EMA9/EMA20 stack**. The Intraday tab sorts by largest
move so the most active names surface first; it reads from Redis and falls back to a
one-off self-fetch if no worker is running.

**Architecture** (matches [ROADMAP.md](ROADMAP.md) §2): a pluggable **feed**
(`realtime/feed.py`, yfinance prototype → Alpaca/Polygon later) → **indicators** →
a **Redis snapshot + stream** (`realtime/store.py`, degrades gracefully if Redis is
down) → Celery task `refresh_intraday` → the window. Provider note: yfinance is
*polled and delayed*; true sub-second streaming arrives with a licensed WebSocket
feed.

---

## Alert engine (Phase 3, Increment 1)

User-defined rules over the live intraday indicators, evaluated every minute by the
same `refresh_intraday` pass and shown on the **🔔 Alerts** tab (with a live count
badge; newest alert also flashes in the status bar).

- **Rules** (`alert_rules` table) AND-combine conditions `{field, op, value}`. Ops:
  `> < >= <= == !=`, `is_true`/`is_false`, and `crosses_above`/`crosses_below`
  (transition vs the previous snapshot). Scope is `*` (whole watchlist) or a ticker.
- **Edge-triggered + cooldown:** an alert fires on the transition *into* the
  matching state, then stays quiet until it stops matching or the per-rule cooldown
  elapses — no spam from a persistent condition.
- **Five starter rules** seed automatically: oversold-above-VWAP, high-RVOL
  opening-range breakout, breakdown below the range, strong intraday trend, and
  overbought. Add your own via `storage.save_rule(...)`.

```python
from stockpredict import storage
storage.save_rule(
    "AAPL reclaims VWAP",
    conditions=[{"field": "pct_from_vwap", "op": "crosses_above", "value": 0}],
    scope="AAPL", cooldown_sec=900,
)
```

The pure evaluator lives in `alerts/engine.py` (fully unit-tested); state persists
in Redis (`alerts/state.py`) so it survives across workers, with an in-process
fallback. Fired alerts are stored in `alerts_fired`.

---

## News + sentiment (Phase 3, Increment 2)

Per-ticker headlines are pulled every 10 min (Celery `refresh_news`), scored with a
transparent **finance-sentiment lexicon**, and shown on the **📰 News** tab (sortable,
color-coded, double-click opens the article). The aggregate sentiment is **merged
into the intraday snapshot** as `news_sentiment`, so it's both visible and
**alertable** — two news-aware starter rules ship (positive/negative news + volume).

- `news/feed.py` — pluggable feed (yfinance prototype → Benzinga/Polygon).
- `news/sentiment.py` — `score_text(text) -> {score, pos, neg}` with negation
  handling; recency-weighted aggregation. **Pluggable:** replace `score_text` with
  FinBERT (~75% on Benzinga) or an LLM ensemble without touching callers.
- `news/service.py` — fetch → score → publish to Redis (`news:latest`, `news:headlines`).

The lexicon is a deliberately explainable baseline and is weaker than FinBERT
(e.g. it scores "profit warning" as mildly positive because of "profit") — treat
sentiment as a rough tilt, and upgrade the scorer for production.

---

## Scanners (Phase 3, Increment 3)

A scanner is a live **filtered + ranked** view over the whole intraday snapshot —
"show me everything matching X right now". Pick one from the dropdown on the
**🔍 Scanners** tab; results refresh every 20s with a match count.

Ten built-in scans ship in `scanners/library.py`: Top Gainers/Losers, Unusual
Volume, Opening-Range Breakouts, Breakdowns, Oversold, Overbought, Above VWAP +
EMA stack, and Positive/Negative News Movers. Filtering **reuses the alert engine's
operators** (`alerts/engine._check`) so semantics never diverge; add a scan by
appending a `{name, filters, sort, desc}` dict.

```python
from scanners.service import run_named
run_named("Unusual Volume (RVOL>1.5)", limit=20)
```

---

## Alert delivery (Phase 3, Increment 4)

Fired alerts are pushed to **notification channels** so they reach you even when the
window isn't focused. Ships a Windows **desktop-toast** channel (`winotify`) and an
always-on **log** channel; email/Telegram slot in behind the same `Notifier`
interface (`notify/channels.py`).

- Delivery is wired into `alerts.service` — every caller (Celery worker, ingestor,
  app) notifies once. Cross-process **de-duplication** is handled by the alert
  engine's edge-trigger + cooldown (shared Redis state), so the same alert never
  toasts twice.
- Toasts are **capped per cycle** (`STOCKPREDICT_MAX_TOASTS`, default 4); extras
  collapse into one summary toast. Disable with `STOCKPREDICT_TOAST=0`.
- Each toast links to the ticker's chart (opens in the browser).

---

## Build your own rules & scans — no code (Phase 3, Increment 5)

The engines are fully usable from the UI:

- **🔔 Alerts tab → “＋ New Rule”** opens a builder: name it, set scope (`*` or a
  ticker) and cooldown, then add AND-combined conditions from dropdowns of
  indicator fields and operators (including `crosses_above/below`, `is_true/false`).
  **“Manage Rules”** lists every rule with enable/disable and delete.
- **🔍 Scanners tab → “＋ New Scan”** builds a custom scan (filters + sort field +
  direction); it’s saved to the DB and appears in the dropdown alongside the
  built-ins. **“Delete”** removes a custom scan (built-ins are protected).

Custom rules persist in `alert_rules`, custom scans in `custom_scans`, so they
survive restarts and are picked up by the background Celery workers too.

---

## Why three different models?

The single most important design decision: **different horizons are driven by
different, sometimes opposite, phenomena.** Using one momentum signal for all
three would be wrong. The academic literature is consistent on this:

| Horizon | Dominant effect | What the app rewards |
|---|---|---|
| **Next week** | **Short-term reversal** — last week's losers tend to bounce, winners give back | *Negative* recent 1-wk / 1-mo return, **low volatility**, small quality tilt |
| **Next month** | Mixed — mild reversal + intermediate (3–6 mo) momentum | 3- & 6-month momentum, quality, trend, mild 1-mo reversal |
| **Next year** | **Momentum (12-1)** + **quality/value** | Trailing 12-mo return *skipping the last month*, quality scorecard, 200-day trend, cheapness |

The "12-1" construction (12-month return excluding the most recent month) is the
standard academic momentum definition — the last month is dropped *precisely
because* short-term reversal contaminates it.

### How a signal becomes an estimated return
1. Each raw factor is **z-scored cross-sectionally** within the current universe
   (winsorized at ±3σ), so a stock is judged relative to its peers right now.
2. Per-horizon weights (in `model.py → HORIZON_WEIGHTS`) blend the z-scores into
   one composite signal.
3. The composite maps to an estimated return: `base_drift + tilt`, where the tilt
   is **capped** per horizon (`MAX_TILT` = 4% / 9% / 35%) so an extreme momentum
   reading produces a *sane* estimate, not a projected quadruple.
4. A **±1σ range** is drawn from each stock's own realized volatility, scaled to
   the horizon — wider for volatile names.
5. **Confidence (capped at 78%)** reflects data completeness, history length, and
   how far the signal stands out — it is *not* a probability of being right.

Everything is transparent and tunable: open `model.py` and change the weights,
caps, or drift to fit your thesis.

---

## Architecture

```
app.py  (Tkinter window, 3 tabs, live updates via a thread-safe queue)
   │  subscribes to
   ▼
stockpredict/aggregator.py   ← background thread: refresh loop, never blocks UI
   ├─ data.py        fetch_prices() bulk download + disk cache
   │                 get_fundamentals() rotating, TTL-cached, chunked
   ├─ factors.py     price → returns, momentum, vol, MAs, 52w-high; quality/value
   └─ model.py       z-score → per-horizon blend → estimated return + confidence
```

- **Continuous aggregation:** a daemon thread re-pulls prices each interval and
  refreshes a rotating chunk of fundamentals (slow, one call each) so a large
  universe updates gradually without hammering the feed. Results are cached to
  disk (`~/.stockpredict_cache`) so restarts are warm.
- **Fault tolerance:** one bad ticker or a network blip never sinks a refresh; the
  loop catches everything and retries on the next cycle.

| File | Role |
|---|---|
| `app.py` | Desktop window, tables, detail popups |
| `stockpredict/config.py` | Universe, horizons, refresh cadence |
| `stockpredict/data.py` | yfinance prices + fundamentals, caching |
| `stockpredict/factors.py` | Raw factor computation + quality/value scorecard |
| `stockpredict/model.py` | Cross-sectional z-scoring + per-horizon estimates |
| `stockpredict/aggregator.py` | Background continuous-refresh loop |

---

## Honest expectations & limits

- **Factors are weak, noisy, and time-varying.** Momentum and reversal are
  *statistical tendencies across many names over many periods*, not promises
  about any one stock next week. Expect to be wrong often.
- **Day trading is a losing game for almost everyone** — build this to surface
  *ideas to research on longer horizons*, not for intraday signals.
- **No backtest yet.** The single most valuable upgrade is a backtest harness
  (historical factors → realized forward 1-wk/1-mo/1-yr returns) to validate and
  re-fit the weights, rather than trusting plausible-but-unproven defaults.
- **yfinance is unofficial.** For anything real, move to a licensed data API.
- This is **not investment advice.** Do your own research; consider low-cost index
  funds; nothing here accounts for your situation, taxes, or risk tolerance.

## Sensible next steps
1. **Backtest** the scorecard and re-fit `HORIZON_WEIGHTS` / `MAX_TILT`.
2. Add a **news/sentiment** factor (e.g. Alpha Vantage `NEWS_SENTIMENT`).
3. Add sector-neutral z-scoring (rank within sector) to avoid sector bets.
4. Persist a daily snapshot so you can track estimate-vs-actual over time.

---

### Methodology sources
- Short-term reversal vs. 12-month momentum, and why momentum skips the last month:
  [AlphaArchitect — Short-term Momentum](https://alphaarchitect.com/short-term-momentum/),
  [ScienceDirect — Short-term momentum (almost) everywhere](https://www.sciencedirect.com/science/article/pii/S1042443119300976),
  [Quantpedia — Short Term Reversal Effect](https://quantpedia.com/strategies/short-term-reversal-in-stocks)
- Momentum lookback horizons and the 12-1 construction:
  [ScienceDirect — Time series momentum](https://www.sciencedirect.com/science/article/pii/S0304405X11002613),
  [Quantpedia — Time Series Momentum Effect](https://quantpedia.com/strategies/time-series-momentum-effect)
- Quality / factor interaction:
  [AlphaArchitect — Quality, Factor Momentum, and the Cross-Section of Returns](https://alphaarchitect.com/cross-section-of-returns/)
