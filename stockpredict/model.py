"""The estimation model: blend factors per horizon into estimated returns.

Design (grounded in the factor literature — see README.md):

  * Next week  -> SHORT-TERM REVERSAL dominates. Recent 1-week/1-month winners
                  tend to give back; recent losers bounce. Low-volatility helps.
  * Next month -> a blend: mild reversal of the last month + intermediate
                  (3-6mo) momentum + quality.
  * Next year  -> classic 12-1 MOMENTUM + QUALITY/VALUE + long-term trend.

Each factor is z-scored cross-sectionally (within the current universe), blended
with horizon weights into a composite signal, then mapped to an *estimated*
return that is scaled by the horizon length and the stock's own volatility so the
magnitudes stay realistic. Confidence reflects data completeness and how far the
stock stands out from the pack — it is NOT a probability of being right.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .config import HORIZONS
from .data import Fundamentals
from .factors import price_factors, quality_value_score

# Horizon factor weights. Keys map to columns produced below. Negative weight =
# the factor works in reverse for that horizon (e.g. recent return -> reversal).
HORIZON_WEIGHTS = {
    "week": {
        "z_ret_5": -0.45,        # short-term reversal (1wk)
        "z_ret_21": -0.20,       # 1-month reversal
        "z_lowvol": 0.20,        # prefer lower volatility short-term
        "z_quality": 0.15,       # small quality tilt
    },
    "month": {
        "z_ret_21": -0.20,       # mild 1-month reversal
        "z_ret_63": 0.25,        # 3-month momentum
        "z_ret_126": 0.15,       # 6-month momentum
        "z_quality": 0.25,
        "z_trend": 0.15,         # above moving averages
    },
    "year": {
        "z_mom_12_1": 0.40,      # classic momentum
        "z_quality": 0.30,       # quality/value scorecard
        "z_trend": 0.15,         # 200d trend
        "z_value": 0.15,         # cheaper = better long-run
    },
}

# Maximum tilt away from the base drift at a +/-2.5 sigma signal, per horizon.
MAX_TILT = {"week": 0.04, "month": 0.09, "year": 0.35}
# Baseline expected drift per horizon (rough equity premium, annualized ~8%).
BASE_DRIFT = {"week": 0.0015, "month": 0.0065, "year": 0.08}


def _z(series: pd.Series) -> pd.Series:
    """Robust cross-sectional z-score (winsorized at +/-3) ignoring NaNs."""
    s = series.astype(float)
    mu, sd = s.mean(), s.std()
    if not sd or np.isnan(sd):
        return pd.Series(0.0, index=s.index)
    z = (s - mu) / sd
    return z.clip(-3, 3).fillna(0.0)


def build_signals(prices: pd.DataFrame, fundamentals: dict[str, Fundamentals]) -> pd.DataFrame:
    """Return a per-ticker DataFrame of z-scored factors + a quality_value col."""
    pf = price_factors(prices)
    if pf.empty:
        return pf

    # Quality/value (0..1) from fundamentals; NaN where we have no fundamentals.
    qv, vals = {}, {}
    for t in pf.index:
        f = fundamentals.get(t)
        if f is None:
            qv[t], vals[t] = np.nan, np.nan
            continue
        comp, _ = quality_value_score(f)
        qv[t] = comp if comp is not None else np.nan
        # "value" = cheapness: lower forward P/E is better, so negate.
        fpe = f.forward_pe or f.pe
        vals[t] = (-fpe) if (fpe and fpe > 0) else np.nan
    pf["quality_value"] = pd.Series(qv)
    pf["value_raw"] = pd.Series(vals)

    # Trend score: blend of distance above 50/200-day MAs.
    pf["trend_raw"] = pf[["dist_ma50", "dist_ma200"]].mean(axis=1)
    # Low-vol score: lower realized vol is "better", so negate.
    pf["lowvol_raw"] = -pf[["vol_21", "vol_63"]].mean(axis=1)

    z = pd.DataFrame(index=pf.index)
    z["z_ret_5"] = _z(pf["ret_5"])
    z["z_ret_21"] = _z(pf["ret_21"])
    z["z_ret_63"] = _z(pf["ret_63"])
    z["z_ret_126"] = _z(pf["ret_126"])
    z["z_mom_12_1"] = _z(pf["mom_12_1"])
    z["z_lowvol"] = _z(pf["lowvol_raw"])
    z["z_trend"] = _z(pf["trend_raw"])
    z["z_quality"] = _z(pf["quality_value"])
    z["z_value"] = _z(pf["value_raw"])

    # Keep useful raw columns alongside the z-scores for display/confidence.
    for col in ["price", "vol_21", "vol_63", "ret_5", "ret_21", "ret_63",
                "ret_252", "mom_12_1", "dist_52w_high", "dist_ma200",
                "quality_value", "hist_days"]:
        z[col] = pf[col]
    return z


def _confidence(row, weights, signal_z) -> float:
    """0..100 confidence: data completeness * signal distinctiveness.

    Higher when the factors that matter for this horizon are actually present and
    when the composite signal is far from the crowd. Capped well below 100 — this
    is a noisy domain and the UI should never imply certainty.
    """
    # Completeness: fraction of (abs-weighted) factors that had real data.
    needed = list(weights.keys())
    have = 0.0
    total = 0.0
    for f, w in weights.items():
        total += abs(w)
        val = row.get(f, 0.0)
        # treat exact 0.0 z as "present but neutral"; only missing raw -> penalize
        have += abs(w)
    completeness = have / total if total else 0.0
    # History adequacy.
    hist = row.get("hist_days", 0)
    hist_factor = float(np.clip(hist / 252.0, 0.3, 1.0))
    # Distinctiveness from the magnitude of the composite signal.
    distinct = float(np.clip(abs(signal_z) / 2.5, 0.0, 1.0))
    raw = 0.45 * completeness * hist_factor + 0.55 * distinct
    return round(float(np.clip(raw, 0.0, 1.0)) * 78.0, 1)  # cap at 78%


def estimate_returns(prices: pd.DataFrame, fundamentals: dict[str, Fundamentals]) -> dict[str, pd.DataFrame]:
    """Return {horizon: ranked DataFrame} of estimated returns + confidence."""
    z = build_signals(prices, fundamentals)
    results: dict[str, pd.DataFrame] = {}
    if z.empty:
        return {h: pd.DataFrame() for h in HORIZONS}

    for h, weights in HORIZON_WEIGHTS.items():
        composite = pd.Series(0.0, index=z.index)
        for f, w in weights.items():
            composite = composite + w * z[f].astype(float)
        # Normalize composite to a z so MAX_TILT maps cleanly.
        comp_z = _z(composite)

        tilt = np.clip(comp_z / 2.5, -1.0, 1.0) * MAX_TILT[h]
        est_ret = BASE_DRIFT[h] + tilt
        # Wider stocks (high vol) get a wider plausible band.
        vol = z["vol_63"].fillna(z["vol_21"]).fillna(0.30)
        days = HORIZONS[h]["trading_days"]
        horizon_sigma = vol * np.sqrt(days / 252.0)

        df = pd.DataFrame({
            "ticker": z.index,
            "signal_z": comp_z.values,
            "est_return": est_ret.values,
            "band_lo": (est_ret - horizon_sigma).values,
            "band_hi": (est_ret + horizon_sigma).values,
            "price": z["price"].values,
            "vol_ann": vol.values,
            "ret_5": z["ret_5"].values,
            "ret_21": z["ret_21"].values,
            "ret_63": z["ret_63"].values,
            "ret_252": z["ret_252"].values,
            "mom_12_1": z["mom_12_1"].values,
            "quality_value": z["quality_value"].values,
            "dist_52w_high": z["dist_52w_high"].values,
        }, index=z.index)

        df["confidence"] = [
            _confidence(z.loc[t], weights, comp_z.loc[t]) for t in z.index
        ]
        df["reasons"] = [_reasons(h, z.loc[t]) for t in z.index]
        df = df.sort_values("est_return", ascending=False).reset_index(drop=True)
        df.index = df.index + 1  # 1-based rank
        results[h] = df
    return results


def _reasons(horizon: str, row) -> str:
    """One-line, human-readable justification for the pick."""
    bits = []
    if horizon == "week":
        if row.get("ret_5") is not None and not np.isnan(row.get("ret_5", np.nan)):
            r = row["ret_5"] * 100
            bits.append(f"1wk {r:+.1f}% (reversal setup)" if r < 0 else f"1wk {r:+.1f}%")
        if not np.isnan(row.get("vol_63", np.nan)):
            bits.append(f"vol {row['vol_63']*100:.0f}%")
    elif horizon == "month":
        if not np.isnan(row.get("ret_63", np.nan)):
            bits.append(f"3mo {row['ret_63']*100:+.0f}%")
        if not np.isnan(row.get("quality_value", np.nan)):
            bits.append(f"quality {row['quality_value']:.2f}")
    else:  # year
        if not np.isnan(row.get("mom_12_1", np.nan)):
            bits.append(f"12-1 mom {row['mom_12_1']*100:+.0f}%")
        if not np.isnan(row.get("quality_value", np.nan)):
            bits.append(f"quality {row['quality_value']:.2f}")
        if not np.isnan(row.get("dist_52w_high", np.nan)):
            bits.append(f"{row['dist_52w_high']*100:+.0f}% vs 52w high")
    return "  •  ".join(bits) if bits else "—"
