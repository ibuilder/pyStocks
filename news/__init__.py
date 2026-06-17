"""News + sentiment (Phase 3, Increment 2).

Fetches recent per-ticker headlines (yfinance prototype → Benzinga/Polygon later)
and scores them with a transparent finance-sentiment lexicon. The scorer is behind
a `score_text(text) -> dict` interface, so FinBERT (~75% on Benzinga) or an LLM
ensemble can drop in without touching callers. Aggregated sentiment is merged into
the intraday snapshot so it becomes an alertable field and shows in the window.
"""
