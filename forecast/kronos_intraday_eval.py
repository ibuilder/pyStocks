"""Kronos on its NATIVE domain: intraday 5-minute bars, short horizon.

For each eval timestamp (one mid-session bar per day) we forecast the next H 5m
bars and compare, cross-sectionally, three rankings against the realized next-30min
return: Kronos, a momentum-persistence baseline (last-H return), and (implicitly)
a coin flip via directional hit-rate. This is the setup most favorable to Kronos.

    KRONOS_VARIANT=mini python -u -m forecast.kronos_intraday_eval --tickers 10 --horizon 6
"""
from __future__ import annotations

import argparse
import os

import numpy as np
import pandas as pd

from backtest.engine import _spearman
from stockpredict.config import DEFAULT_WATCHLIST

_OUT = None
CKPT_HEADER = "ts,ic_k,ic_m,hit_k,hit_m,n\n"


def _emit(msg):
    print(msg, flush=True)
    if _OUT:
        _OUT.write(msg + "\n"); _OUT.flush(); os.fsync(_OUT.fileno())


def _load_ckpt(path):
    done = {}
    if os.path.exists(path):
        for line in open(path, encoding="utf-8").readlines()[1:]:
            p = line.strip().split(",")
            if len(p) >= 6:
                done[p[0]] = p
    return done


def _eval_points(index, horizon, session_frac=0.55):
    """One bar per trading day, ~session_frac through the day, with H bars to spare."""
    df = pd.DataFrame({"ts": index}, index=index)
    days = pd.Index([t.date() for t in index])
    pts = []
    for d in pd.unique(days):
        day_idx = index[days == d]
        if len(day_idx) < 20:
            continue
        k = int(len(day_idx) * session_frac)
        if k + horizon < len(day_idx):
            pts.append(day_idx[k])
    return pts


def run(n_tickers=10, horizon=6, max_days=24, ckpt="kronos_intraday_ckpt.csv", out="kronos_intraday_out.txt"):
    global _OUT
    _OUT = open(out, "w", encoding="utf-8")
    step = max(1, len(DEFAULT_WATCHLIST) // n_tickers)
    tickers = list(DEFAULT_WATCHLIST)[::step][:n_tickers]
    _emit(f"Downloading 60d of 5m bars for {len(tickers)} tickers…")

    import yfinance as yf
    raw = yf.download(tickers, period="60d", interval="5m", auto_adjust=True,
                      group_by="ticker", threads=True, progress=False, prepost=False)
    closes = {}
    for t in tickers:
        try:
            s = raw[t]["Close"].dropna() if isinstance(raw.columns, pd.MultiIndex) else raw["Close"].dropna()
            if len(s) > 500:
                closes[t] = s
        except Exception:
            continue
    ohlcv = {t: raw[t][["Open", "High", "Low", "Close", "Volume"]].dropna().rename(columns=str.lower)
             for t in closes}
    close_df = pd.DataFrame(closes).dropna(how="all").sort_index()
    common = close_df.index
    _emit(f"  {len(closes)} tickers x {len(common)} 5m bars")

    pts = _eval_points(common, horizon)[-max_days:]
    _emit(f"  {len(pts)} eval timestamps (horizon={horizon} bars = {horizon*5}min)\n")

    done = _load_ckpt(ckpt)
    if not os.path.exists(ckpt):
        open(ckpt, "w", encoding="utf-8").write(CKPT_HEADER)

    from forecast.kronos_forecaster import KronosForecaster
    kf = KronosForecaster()
    _emit(f"Kronos variant={os.environ.get('KRONOS_VARIANT','small')} ctx={kf.max_context}\n")

    for ts in pts:
        key = str(ts)
        if key in done:
            continue
        i = common.get_loc(ts)
        if i + horizon >= len(common):
            continue
        realized = (close_df.iloc[i + horizon] / close_df.iloc[i] - 1.0)
        kpred, mom = {}, {}
        for t in closes:
            hist = ohlcv[t].loc[:ts]
            if len(hist) < 120 or np.isnan(realized.get(t, np.nan)):
                continue
            # momentum-persistence baseline: last-H return
            try:
                mom[t] = float(hist["close"].iloc[-1] / hist["close"].iloc[-1 - horizon] - 1.0)
            except Exception:
                pass
            try:
                # freq MUST be 5min here — these are 5-minute bars, not daily.
                kpred[t] = kf.expected_return(hist, horizon, sample_count=1, freq="5min")
            except Exception as exc:
                _emit(f"    ! {t} {exc}")
        kpred = pd.Series(kpred).dropna(); mom = pd.Series(mom).dropna()
        cols = kpred.index.intersection(mom.index).intersection(realized.dropna().index)
        if len(cols) < 4:
            continue
        r = realized.loc[cols]
        ic_k = _spearman(kpred.loc[cols], r)
        ic_m = _spearman(mom.loc[cols], r)
        hit_k = float((np.sign(kpred.loc[cols]) == np.sign(r)).mean())
        hit_m = float((np.sign(mom.loc[cols]) == np.sign(r)).mean())
        with open(ckpt, "a", encoding="utf-8") as fh:
            fh.write(f"{ts},{ic_k:.4f},{ic_m:.4f},{hit_k:.4f},{hit_m:.4f},{len(cols)}\n")
            fh.flush(); os.fsync(fh.fileno())
        _emit(f"  {ts:%Y-%m-%d %H:%M}  Kronos IC={ic_k:+.3f} (hit {hit_k*100:.0f}%)  "
              f"Momentum IC={ic_m:+.3f} (hit {hit_m*100:.0f}%)  n={len(cols)}")

    summarize(ckpt)


def summarize(ckpt="kronos_intraday_ckpt.csv"):
    rows = list(_load_ckpt(ckpt).values())
    if not rows:
        _emit("no rows"); return
    a = np.array([[float(x) for x in r[1:5]] for r in rows])
    _emit("\n=========  INTRADAY HEAD-TO-HEAD (5m bars, next 30min)  =========")
    _emit(f"Kronos     mean IC={a[:,0].mean():+.3f}  t={_t(a[:,0]):+.2f}  dir-hit={a[:,2].mean()*100:.1f}%")
    _emit(f"Momentum   mean IC={a[:,1].mean():+.3f}  t={_t(a[:,1]):+.2f}  dir-hit={a[:,3].mean()*100:.1f}%")
    _emit(f"Eval timestamps: {len(rows)}   (dir-hit 50% = coin flip)")


def _t(arr):
    arr = arr[~np.isnan(arr)]
    return arr.mean() / (arr.std(ddof=1) / np.sqrt(len(arr))) if len(arr) > 1 and arr.std(ddof=1) else float("nan")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--tickers", type=int, default=10)
    ap.add_argument("--horizon", type=int, default=6)
    ap.add_argument("--days", type=int, default=24)
    ap.add_argument("--ckpt", default="kronos_intraday_ckpt.csv")
    ap.add_argument("--out", default="kronos_intraday_out.txt")
    ap.add_argument("--summarize", action="store_true")
    a = ap.parse_args()
    if a.summarize:
        _OUT = open(a.out, "w", encoding="utf-8"); summarize(a.ckpt)
    else:
        run(n_tickers=a.tickers, horizon=a.horizon, max_days=a.days, ckpt=a.ckpt, out=a.out)
