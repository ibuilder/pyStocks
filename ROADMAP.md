# stockpredict → Day-Trading Companion: Long-Term Roadmap

**Status:** Draft v1 · Last updated 2026-06-14
**Scope:** Evolve the current 3-horizon estimator (a polling Tkinter desktop app)
into a real-time, Celery-backed **day-trading research & decision-support
companion** that continuously aggregates the most current market data, news, and
signals.

---

## 0. Vision & guardrails (read this first)

**What we are building:** a *companion* that makes a human trader faster and more
disciplined — real-time data aggregation, scanners, news/sentiment, technical
signals, alerts, journaling, and rigorous backtesting/risk tooling.

**What we are NOT building:**
- Not an auto-trader. The tool **never places orders**; it surfaces information and,
  at most, prepares an order ticket the human reviews and submits in their broker.
- Not a promise of profit. Day trading is, per the academic record, a net-losing
  activity for the large majority of retail participants. The product's value is
  *speed, situational awareness, and discipline*, not a magic edge.
- Not investment advice. Every signal is an estimate with wide error bars and ships
  with that framing in the UI.

**Design principles**
1. **Information latency is the product.** Optimize the path from event → screen.
2. **Every signal is explainable** (carry reasons + provenance, like today's app).
3. **Risk tooling is first-class, not a bolt-on** (position sizing, max daily loss,
   R-multiples baked into every workflow).
4. **Validate before trust** — no signal ships to the UI as "actionable" until it
   has a walk-forward backtest with realistic costs/slippage behind it.

---

## 1. Where we are today (baseline)

| Capability | Today |
|---|---|
| Data | yfinance polling (delayed/EOD), bulk daily history |
| Cadence | Background thread, ~15-min refresh |
| Horizons | Week / Month / Year, factor z-scores → capped estimates |
| Delivery | Tkinter desktop window, 3 tabs |
| Persistence | Pickle disk cache |
| Compute | Synchronous in one process |

**Gap to target:** sub-second data, intraday signals, news/sentiment, a real
message-bus architecture, alerting, backtesting, and a UI that can stream.

---

## 2. Target architecture (hybrid: streaming bus + Celery)

The single most important lesson from the research: **Celery is the wrong tool for
the per-tick firehose** (it tops out ~8k tasks/sec on a Redis broker and adds
queue latency), but it is the *right* tool for scheduled, guaranteed, retryable
work. So we split responsibilities:

```
                 ┌─────────────────────────────────────────────────────┐
                 │  PROVIDERS (WebSocket + REST)                         │
                 │  prices/quotes · trades · news · fundamentals        │
                 └───────────────┬──────────────────────┬──────────────┘
        real-time (sub-second)   │                      │  scheduled / on-demand
                                 ▼                      ▼
        ┌────────────────────────────────┐   ┌──────────────────────────┐
        │ INGESTOR (asyncio, long-lived)  │   │ Celery Beat (scheduler)  │
        │  one ws consumer per provider   │   │  pre-market scan, EOD     │
        │  normalizes → Redis Streams     │   │  backtest, fundamentals,  │
        └───────────────┬────────────────┘   │  model retrain, cleanup   │
                        │ XADD                 └────────────┬─────────────┘
                        ▼                                   │ enqueue
              ┌───────────────────┐                         ▼
              │   REDIS            │◄──── results ──── ┌───────────────────┐
              │  Streams (ticks,   │                   │ Celery WORKERS     │
              │   news, signals)   │──── consume ─────►│ indicators, FinBERT│
              │  pub/sub (UI push) │                   │ /LLM sentiment,    │
              │  cache + results   │◄──── publish ─────│ alert eval, scans, │
              └─────────┬─────────┘                    │ backtests          │
                        │ pub/sub / SSE / ws            └───────────────────┘
                        ▼
        ┌────────────────────────────────────────────┐
        │ UI:  FastAPI gateway → web dashboard         │
        │      (and/or the existing desktop window      │
        │       upgraded to consume the stream)         │
        └────────────────────────────────────────────┘
```

**Why this split**
- **Ingestor (asyncio):** persistent WebSocket connections don't belong in
  short-lived Celery tasks. One supervised consumer per provider, auto-reconnect,
  writes normalized events to **Redis Streams** (durable, replayable, consumer
  groups for fan-out).
- **Celery Beat + workers:** everything cron-like or heavy and retryable —
  pre-market scanners, per-symbol indicator/sentiment computation, alert-rule
  evaluation, nightly backtests, fundamentals refresh, model retrain. Celery gives
  us guaranteed delivery, retries with backoff, rate-limiting, and scheduling
  (we already use this pattern in the original `celery_app.py`).
- **Redis** is broker + result backend + the streaming bus + hot cache. Add
  **TimescaleDB/Postgres** for durable bars/journal, **Parquet** for the backtest
  data lake.
- **FastAPI gateway** turns Redis pub/sub into Server-Sent Events / WebSocket for a
  browser dashboard; the existing Tkinter app can also subscribe during transition.

---

## 3. Data-provider strategy

Start free for prototyping, design the provider layer (we already have a pluggable
`data.py`) so upgrading is a config change, then move to a real-time license.

| Provider | Real-time | Free tier | Transport | Best for | Notes |
|---|---|---|---|---|---|
| **Alpaca** | Yes (US equities) | Genuinely free, no card | REST + WS | Prototype real-time + paper-trading | Also a broker → paper trading API for safe order-ticket testing |
| **Finnhub** | ~<100ms | Generous (60 req/min) | REST + WS | Free WS streaming, dev | Good news endpoint too |
| **Polygon (Massive)** | <10ms | None ($99+/mo) | REST + WS | Production low-latency + **Benzinga news** | Benzinga premium feed now distributed via Polygon |
| **Databento** | Yes, institutional | Pay-as-you-go (~$8/mo) | REST + WS | Tick/L2 depth, prebuilt indicators | Cheap entry to institutional data |
| **yfinance** | No (delayed/EOD) | Free (unofficial) | REST | Current baseline only | Keep as offline fallback |

**News & sentiment:** Benzinga-via-Polygon for trader-grade headlines (analyst
moves, price targets, M&A, guidance); score with **FinBERT** (≈75% on Benzinga
text) as the cheap baseline, optionally an **LLM ensemble** for nuance. Keep
sentiment as an explainable factor with the source headline attached.

**Recommendation:** **Alpaca (free real-time + paper trading) for Phases 2–3**,
graduate to **Polygon/Databento** when latency and depth start to matter.

---

## 4. Phased roadmap

Estimates assume part-time solo dev; compress with more hands. Each phase ends with
a **demoable** increment and explicit exit criteria.

### Phase 0 — Foundation & de-risking ✅ DONE
*Make the project production-shaped before adding surface area.*
- Move from pickle to **Postgres/TimescaleDB** (bars, signals, journal) + keep
  Redis cache.
- Stand up **Redis** + **Celery Beat/worker** skeleton (port the original
  `celery_app.py` schedule; add `task_acks_late`, rate limits).
- Config via `.env`; structured logging; basic **pytest** harness for `model.py`.
- Provider interface hardened; add **Alpaca** as a provider (still daily for now).
- **Exit:** `celery -A ... beat/worker` runs a scheduled daily screen that writes
  to Postgres and the desktop app reads from it.

### Phase 1 — Backtesting & validation harness ✅ DONE (initial cut) — *do this before more signals*
*Nothing becomes "actionable" without this. This is the highest-leverage phase.*
- Integrate **VectorBT** (vectorized, fast parameter sweeps) for research; keep
  **Backtrader** option for event-driven realism on single instruments.
- Historical data lake (Parquet) of bars + point-in-time fundamentals.
- **Walk-forward** cross-validation, realistic **commissions + slippage**, and
  out-of-sample reporting; flag overfitting (deflated Sharpe, # trials penalty).
- Backtest the *existing* week/month/year factors → re-fit `HORIZON_WEIGHTS`,
  `MAX_TILT` from evidence instead of priors.
- **Exit:** one-command backtest produces an OOS tearsheet; weekly Celery Beat job
  re-runs it and stores results.

### Phase 2 — Real-time market data spine (3–4 weeks) — 🚧 Increment 1 DONE
*The "Celery in the background for the most current information" core.*
- **Ingestor** service (asyncio) consuming Alpaca/Finnhub WS → **Redis Streams**
  (trades, quotes, minute bars), with reconnect/backfill.
- Celery workers compute **intraday indicators** per symbol off the stream
  (VWAP, EMA stack, RSI, ATR, relative volume, opening-range, gap %).
- **FastAPI gateway** + a **web dashboard** (live watchlist, streaming quotes,
  intraday chart). Desktop app can subscribe too during transition.
- **Exit:** a watchlist updates sub-second in the browser; indicators recompute
  live; Celery Beat snapshots EOD bars to the data lake.
- **Increment 1 (done):** pluggable intraday feed → indicators (VWAP, RVOL, RSI,
  ATR, EMA stack, opening-range) → Redis snapshot/stream → Celery `refresh_intraday`
  (every minute, market hours) → **⚡ Intraday tab** in the desktop window. Prototype
  feed is polled yfinance; remaining work: licensed WebSocket feed for true
  sub-second streaming, the FastAPI/browser dashboard, and EOD bars → data lake.

### Phase 3 — Scanners, news, sentiment & alerts (3–4 weeks) — 🚧 Alerts + News + Scanners DONE
*Where it becomes a real "companion."*
- **Real-time scanners** (momentum, gap-and-go, unusual volume, 52w breakouts,
  halts/resumes) as Celery workers over the stream + Redis-cached universe.
- **News ingestion** (Benzinga/Polygon) → FinBERT/LLM **sentiment** worker →
  ticker-tagged, explainable, with source link.
- **Alert engine:** user-defined rules (price/indicator/news/scanner triggers)
  evaluated by Celery; delivery via in-app + push/email/Telegram; throttling.
- **Exit:** "alert me when AAPL crosses VWAP with positive breaking news and RVOL>2"
  works end-to-end, with the triggering evidence attached.
- **Increment 1 (done):** rule engine over intraday indicators — AND-combined
  conditions, `crosses_above/below`, edge-trigger + cooldown, 5 seeded rules, fired
  alerts persisted and shown on the **🔔 Alerts tab** with the triggering values.
- **Increment 2 (done):** news ingestion + transparent lexicon **sentiment**, merged
  into the intraday snapshot as the alertable `news_sentiment` field, shown on the
  **📰 News tab**, with two news-aware starter rules. Scorer is pluggable for
  FinBERT/LLM.
- **Increment 3 (done):** real-time market-wide **scanners** — 10 built-in scans
  (gainers/losers, unusual volume, ORB breakouts, oversold/overbought, VWAP+EMA,
  news movers) as a live filtered+ranked **🔍 Scanners tab**; filtering reuses the
  alert operators.
- **Increment 4 (done):** **alert delivery** — pluggable notification channels with
  a Windows desktop-toast channel (capped/summarized per cycle, chart deep-link) and
  a log channel; wired into `alerts.service` with cross-process de-dup via the engine
  cooldown. Email/Telegram slot in behind the same interface.
- **Increment 5 (done):** **no-code builders** — UI dialogs to create alert rules
  (fields/ops/values, scope, cooldown) and custom scans (filters + sort), plus a
  rule manager (enable/disable/delete). Custom rules/scans persist in the DB and are
  used by the background workers.
  Remaining: **FinBERT/LLM** sentiment upgrade, trader-grade news feed
  (Benzinga/Polygon), email/Telegram channels.

### Phase 4 — Trader workflow & risk management (3–4 weeks)
*Discipline features — the part that actually helps P&L.*
- **Position sizing & risk calculator** (fixed-% risk, R-multiples, stop distance,
  max position, buying-power checks).
- **Daily risk governor:** max daily loss / max trades / cool-down lockout.
- **Trade journal** (auto-captured from broker fills or manual), tagging, and
  analytics (win rate, expectancy, MAE/MFE, time-of-day edge).
- **Order-ticket builder** (review-only): pre-fills a ticket the user submits in
  their broker. **No auto-execution.** Optional **paper-trading** via Alpaca for
  safe practice.
- **Exit:** a trade can be sized, journaled, and reviewed end-to-end; risk governor
  enforces limits.

### Phase 5 — Intelligence, scale & polish (ongoing)
- **ML/LLM layer:** sequence models (e.g., FinBERT-LSTM) and an LLM "analyst" that
  *summarizes* the case for/against a setup (never an instruction to trade).
- **Multi-account / multi-user**, auth, encrypted secrets, role-based access.
- **Observability:** Flower (Celery), Prometheus/Grafana, dead-letter queues,
  data-quality monitors (stale-feed, gap, outlier detection).
- **Packaging:** Dockerized services; one-command `docker compose up`.
- **Compliance review** before any distribution (see §6).

---

## 5. Cross-cutting concerns

- **Data quality:** stale-feed watchdogs, outlier/halt detection, corporate-action
  adjustment, point-in-time correctness (no lookahead) — enforced in the lake.
- **Latency budget:** measure event→screen at every hop; alert on regressions.
- **Reliability:** Celery `acks_late` + idempotent tasks; ingestor supervised with
  auto-reconnect + Redis Streams replay; DLQ for poison messages.
- **Security:** secrets in a vault/.env (never in code); API keys least-privilege;
  encrypt journal/PII at rest.
- **Testing:** unit (factors/model), integration (stream→worker→Redis), and
  backtest-as-regression-test for signal changes.

## 6. Compliance & honesty (don't skip)

- **No personalized advice / no auto-trading** keeps us clear of acting as an
  investment adviser or broker; if the product is ever sold or distributed, get a
  **securities attorney** review (publisher's-exclusion limits, state rules).
- Persistent **risk disclaimers** in-app; surface the base-rate reality of day
  trading in onboarding.
- If brokerage integration is added, follow each broker's API ToS and PDT rules.

## 7. Definition of success (KPIs)

- **Technical:** event→screen p95 latency; feed uptime; backtest reproducibility;
  alert precision (true triggers / total).
- **Product:** does it measurably speed up the user's research loop and enforce
  their risk rules? Journal adherence; reduction in rule-breaking trades.
- **Honesty check:** every "actionable" signal traces to a walk-forward backtest
  with costs. If it can't, it's labeled "experimental."

---

## 8. Suggested immediate next steps
1. **Phase 0** kickoff: add Redis + Celery skeleton and Postgres, port the daily
   screen to a Beat task. *(Lowest risk, unblocks everything.)*
2. In parallel, sign up for a **free Alpaca** key (real-time + paper trading).
3. Start **Phase 1 backtesting** early — it tells us which signals are worth
   streaming before we spend effort streaming them.

---

### Sources
- Real-time data APIs: [Alpaca Data](https://alpaca.markets/data) · [Best Real-Time Stock Data APIs 2026 (Medium)](https://medium.com/coinmonks/the-7-best-real-time-stock-data-apis-for-investors-and-developers-in-2026-in-depth-analysis-61614dc9bf6c) · [Market Data APIs for Algorithmic Trading 2026 (Alphanume)](https://www.alphanume.com/blog/best-market-data-apis-for-algorithmic-trading-in-2026)
- Celery vs Redis Streams architecture: [Redis vs Celery (Markaicode)](https://markaicode.com/vs/redis-vs-celery/) · [FastAPI + Celery + Redis (Medium)](https://medium.com/@shaikhasif03/building-scalable-background-jobs-with-fastapi-celery-redis-e43152829c61) · [Real-time notifications with Celery, Redis & WebSockets (Medium)](https://medium.com/@chiheb.mhamdi/real-time-notification-using-celery-redis-and-web-sockets-with-django-704175c3182c)
- Day-trading tool features: [Best Real-Time Market Alert Platforms 2026 (NowNews)](https://nownews.dev/blog/best-real-time-market-alert-platforms-2026) · [Top News Filtering Tools for Traders (LuxAlgo)](https://www.luxalgo.com/blog/top-7-news-filtering-tools-for-traders/) · [Best Day Trading Alerts 2026 (DayTrading.com)](https://www.daytrading.com/alerts)
- News sentiment / FinBERT-LLM: [FinBERT for stock movement (arXiv)](https://arxiv.org/html/2306.02136v2) · [LLM sentiment on the S&P 500 (arXiv)](https://arxiv.org/html/2507.09739v1) · [Best Financial News API for Trading 2026 (APITube)](https://apitube.io/blog/post/best-financial-news-api-trading)
- Backtesting: [The Python Backtesting Landscape 2026](https://python.financial/) · [VectorBT vs Zipline vs Backtrader (Medium)](https://medium.com/@trading.dude/battle-tested-backtesters-comparing-vectorbt-zipline-and-backtrader-for-financial-strategy-dee33d33a9e0) · [Intraday backtesting with VectorBT (PyQuant)](https://www.pyquantnews.com/the-pyquant-newsletter/intraday-backtesting-with-vectorbt-pro)
