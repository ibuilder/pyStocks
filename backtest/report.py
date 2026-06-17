"""Render a backtest into a self-contained HTML tearsheet with an equity curve."""
from __future__ import annotations

import base64
import io
from datetime import datetime
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from stockpredict.config import CACHE_DIR
from .engine import BacktestResult, RAW_FOR_Z

REPORT_DIR = Path(CACHE_DIR) / "reports"
REPORT_DIR.mkdir(parents=True, exist_ok=True)


def _equity_png(res: BacktestResult) -> str:
    fig, ax = plt.subplots(figsize=(8, 3.6), dpi=110)
    eq_s = (1 + res.strat_returns).cumprod()
    eq_b = (1 + res.bench_returns).cumprod()
    ax.plot(eq_s.index, eq_s.values, label=f"Strategy (top {res.top_n})", lw=2, color="#3fb950")
    ax.plot(eq_b.index, eq_b.values, label="Equal-weight universe", lw=1.5, color="#8b98a9", ls="--")
    ax.set_title(f"{res.horizon.title()} horizon — growth of $1 (net of {res.cost_bps:.0f}bps)")
    ax.legend(loc="upper left", fontsize=8)
    ax.grid(alpha=0.2)
    fig.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format="png")
    plt.close(fig)
    return base64.b64encode(buf.getvalue()).decode()


def _fmt(x, pct=False):
    if x is None or x != x:
        return "—"
    return f"{x*100:+.1f}%" if pct else f"{x:.2f}"


def render(results: dict[str, BacktestResult], wf: dict | None = None) -> Path:
    """Write an HTML tearsheet for one or more horizons. Returns the path."""
    rows = ""
    charts = ""
    for h, res in results.items():
        m = res.metrics
        png = _equity_png(res)
        charts += f'<h3>{h.title()}</h3><img src="data:image/png;base64,{png}"/>'
        rows += f"""
        <tr><td>{h}</td>
            <td>{m['periods']}</td>
            <td class="{_cls(m['strat_cagr'])}">{_fmt(m['strat_cagr'], True)}</td>
            <td>{_fmt(m['bench_cagr'], True)}</td>
            <td class="{_cls(m['excess_cagr'])}">{_fmt(m['excess_cagr'], True)}</td>
            <td>{_fmt(m['strat_sharpe'])}</td>
            <td>{_fmt(m['max_drawdown'], True)}</td>
            <td>{_fmt(m['hit_rate'], True)}</td>
            <td class="{_cls(m['ic_mean'])}">{_fmt(m['ic_mean'])}</td>
            <td>{_fmt(m['ic_t_stat'])}</td>
        </tr>"""

    # weight comparison (current vs evidence-based) if walk-forward provided
    wf_html = ""
    if wf:
        for h, d in wf.items():
            tc, ts = d["test_current"].metrics, d["test_suggested"]
            sw = ", ".join(
                "%s=%+.2f" % (k.replace("z_", ""), v)
                for k, v in d["train_suggested_weights"].items()
            )
            wf_html += f"""<tr><td>{h}</td>
                <td>{_fmt(tc['strat_cagr'], True)}</td>
                <td>{_fmt(ts['strat_cagr'], True)}</td>
                <td>{_fmt(tc['ic_mean'])}</td>
                <td style="font-size:11px">{sw}</td></tr>"""

    warns = sorted({w for res in results.values() for w in res.warnings})
    warn_html = "".join(f"<li>{w}</li>" for w in warns)

    html = f"""<!doctype html><html><head><meta charset="utf-8">
<title>stockpredict backtest tearsheet</title>
<style>
 body{{font-family:Segoe UI,Arial,sans-serif;background:#0f1419;color:#e6edf3;margin:0;padding:28px;}}
 h1{{margin:0 0 4px}} .sub{{color:#8b98a9;margin-bottom:20px}}
 table{{border-collapse:collapse;width:100%;margin:10px 0 24px;font-size:13px}}
 th,td{{border:1px solid #222d3d;padding:7px 10px;text-align:right}}
 th{{background:#1a2230;color:#8b98a9;text-align:right}} td:first-child,th:first-child{{text-align:left}}
 .pos{{color:#3fb950}} .neg{{color:#f85149}}
 img{{max-width:760px;border:1px solid #222d3d;border-radius:6px;margin:6px 0 18px}}
 .warn{{background:#241a00;border:1px solid #d29922;border-radius:6px;padding:12px 16px;color:#e3b341}}
 .warn li{{margin:3px 0}} h3{{color:#4fa3ff;margin:18px 0 6px}}
 code{{background:#1a2230;padding:1px 5px;border-radius:3px}}
</style></head><body>
<h1>📈 stockpredict — backtest tearsheet</h1>
<div class="sub">Generated {datetime.now():%Y-%m-%d %H:%M} · price-factor model, point-in-time,
non-overlapping walk-forward · net of costs</div>

<h2>Performance by horizon</h2>
<table><tr>
 <th>Horizon</th><th>Samples</th><th>Strat CAGR</th><th>Bench CAGR</th><th>Excess</th>
 <th>Sharpe</th><th>Max DD</th><th>Hit rate</th><th>IC</th><th>IC t-stat</th></tr>
 {rows}
</table>
<p class="sub">The metric that matters most for a ranking model is the <b>Information
Coefficient (IC)</b> — rank correlation between predicted score and realized forward
return. An IC t-stat above ~2 is the bar for "the signal is real".</p>

{('<h2>Re-fit check: current vs evidence-based weights (out-of-sample)</h2>'
  '<table><tr><th>Horizon</th><th>Current CAGR</th><th>Suggested CAGR</th>'
  '<th>Current IC</th><th>Train-derived suggested weights</th></tr>' + wf_html + '</table>') if wf else ''}

<h2>Equity curves</h2>
{charts}

<h2>⚠ Caveats</h2>
<div class="warn"><ul>{warn_html}</ul></div>
</body></html>"""

    out = REPORT_DIR / f"tearsheet_{datetime.now():%Y%m%d_%H%M%S}.html"
    out.write_text(html, encoding="utf-8")
    return out


def _cls(x):
    if x is None or x != x:
        return ""
    return "pos" if x >= 0 else "neg"
