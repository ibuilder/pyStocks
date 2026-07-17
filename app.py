"""stockpredict — desktop window for multi-horizon stock return estimates.

Run:  python app.py

This is a research / idea-generation tool, NOT investment advice and NOT a
guarantee of future returns. Every number is an estimate with wide error bars.
"""
from __future__ import annotations

import csv
import queue
import re
import threading
import time
import tkinter as tk
import webbrowser
from tkinter import ttk, messagebox, filedialog

from stockpredict.aggregator import DataAggregator
from stockpredict.config import HORIZONS, config, DEFAULT_REFRESH_SECONDS
from stockpredict import storage, userprefs, market
from realtime import store as intraday_store
from news import service as news_service
from scanners import service as scanners_service
from alerts.engine import SUPPORTED_OPS, SUPPORTED_FIELDS, FIELD_LABELS

# ------------------------------------------------------------------ theme ---
BG = "#0f1419"
PANEL = "#1a2230"
PANEL2 = "#222d3d"
FG = "#e6edf3"
MUTED = "#8b98a9"
ACCENT = "#4fa3ff"
GREEN = "#3fb950"
RED = "#f85149"
AMBER = "#d29922"

COLUMNS = [
    ("rank", "#", 40),
    ("ticker", "Ticker", 70),
    ("est", "Est. Return", 100),
    ("band", "Range (1σ)", 140),
    ("conf", "Confidence", 150),
    ("price", "Price", 80),
    ("reasons", "Why", 360),
]

INTRADAY_COLUMNS = [
    ("ticker", "Ticker", 70),
    ("last", "Last", 80),
    ("open", "% Open", 80),
    ("vwap", "vs VWAP", 90),
    ("rvol", "RVOL", 70),
    ("rsi", "RSI", 60),
    ("atr", "ATR", 70),
    ("orbreak", "OR Break", 90),
    ("ema", "EMA Stack", 90),
    ("bars", "Bars", 55),
]

ALERT_COLUMNS = [
    ("time", "Time", 90),
    ("ticker", "Ticker", 70),
    ("rule", "Rule", 280),
    ("details", "Details", 560),
]

NEWS_COLUMNS = [
    ("ticker", "Ticker", 70),
    ("sent", "Sentiment", 110),
    ("time", "Time", 130),
    ("title", "Headline", 600),
    ("pub", "Source", 150),
]

SCAN_COLUMNS = [
    ("ticker", "Ticker", 75),
    ("last", "Last", 90),
    ("open", "% Open", 85),
    ("vwap", "vs VWAP", 90),
    ("rvol", "RVOL", 75),
    ("rsi", "RSI", 65),
    ("atr", "ATR", 75),
    ("news", "News", 80),
]


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.prefs = userprefs.load()
        self.title("stockpredict — day-trading research companion")
        self.geometry(self.prefs.get("geometry", "1180x720"))
        self.configure(bg=BG)
        self.minsize(960, 560)

        # Apply persisted universe before the aggregator starts.
        if self.prefs.get("universe_source") in ("watchlist", "sp500"):
            config.universe_source = self.prefs["universe_source"]
        if self.prefs.get("refresh_seconds"):
            config.refresh_seconds = int(self.prefs["refresh_seconds"])

        self._queue: queue.Queue = queue.Queue()
        self.results = None
        self.meta = {}
        self.trees: dict[str, ttk.Treeview] = {}
        self._named_trees: dict = {}        # name -> tree (for width persistence)
        self._tree_sort: dict = {}          # tree -> (col_id, descending)
        self._last_refresh_ts = 0.0
        self._intraday_bar_cache: dict = {} # ticker -> (ts, bars) for the chart

        self._build_style()
        self._build_header()
        self._build_controls()
        self._build_tabs()
        self._build_statusbar()
        self._restore_col_widths()

        self.agg = DataAggregator(
            on_update=lambda r, m: self._queue.put(("update", (r, m))),
            on_status=lambda s: self._queue.put(("status", s)),
        )
        self._intraday_started = False
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.after(150, self._drain_queue)
        self._load_last_snapshot()
        self.agg.start()
        self.after(200, self._raise_window)
        self.after(500, self._poll_intraday)
        self._alert_seen = 0
        self.after(900, self._poll_alerts)
        self._news_started = False
        self.after(1300, self._poll_news)
        self.after(1700, self._poll_scanners)
        self.after(1000, self._tick)

    def _load_last_snapshot(self):
        """Show the most recent saved run instantly (may be from a Celery job)."""
        try:
            results = storage.load_latest()
        except Exception:
            results = {}
        if results:
            self.results = results
            self._render(results)
            self._set_status("Showing last saved run — refreshing live data…")
        else:
            self._set_status("Starting up — first data pull in progress…")

    def _raise_window(self):
        """Force the window to the foreground on launch (Windows can bury it)."""
        try:
            self.deiconify()
            self.lift()
            self.attributes("-topmost", True)
            self.focus_force()
            self.after(800, lambda: self.attributes("-topmost", False))
        except Exception:
            pass

    # ---------------------------------------------------------------- style
    def _build_style(self):
        st = ttk.Style(self)
        try:
            st.theme_use("clam")
        except Exception:
            pass
        st.configure("TFrame", background=BG)
        st.configure("Panel.TFrame", background=PANEL)
        st.configure("TLabel", background=BG, foreground=FG, font=("Segoe UI", 10))
        st.configure("Muted.TLabel", background=BG, foreground=MUTED, font=("Segoe UI", 9))
        st.configure("Head.TLabel", background=BG, foreground=FG, font=("Segoe UI Semibold", 17))
        st.configure("Sub.TLabel", background=BG, foreground=MUTED, font=("Segoe UI", 9))
        st.configure("TButton", font=("Segoe UI", 9), padding=6)
        st.configure("Accent.TButton", font=("Segoe UI Semibold", 9), padding=6)
        st.configure("TCheckbutton", background=BG, foreground=FG, font=("Segoe UI", 9))
        st.map("TCheckbutton", background=[("active", BG)])
        st.configure("TCombobox", fieldbackground=PANEL2, background=PANEL2, foreground=FG)

        st.configure("Treeview",
                     background=PANEL, fieldbackground=PANEL, foreground=FG,
                     rowheight=26, font=("Segoe UI", 10), borderwidth=0)
        st.configure("Treeview.Heading",
                     background=PANEL2, foreground=FG,
                     font=("Segoe UI Semibold", 10), relief="flat")
        st.map("Treeview", background=[("selected", "#2d4a73")])
        st.configure("TNotebook", background=BG, borderwidth=0)
        st.configure("TNotebook.Tab", background=PANEL, foreground=MUTED,
                     padding=(20, 8), font=("Segoe UI Semibold", 10))
        st.map("TNotebook.Tab",
               background=[("selected", PANEL2)],
               foreground=[("selected", ACCENT)])

    # --------------------------------------------------------------- header
    def _build_header(self):
        hdr = ttk.Frame(self, style="TFrame")
        hdr.pack(fill="x", padx=18, pady=(14, 4))
        ttk.Label(hdr, text="📈  stockpredict", style="Head.TLabel").pack(anchor="w")
        ttk.Label(
            hdr,
            text="Ranked return estimates for the next week, month, and year — "
                 "from momentum, reversal, quality/value & low-volatility factors.",
            style="Sub.TLabel",
        ).pack(anchor="w")

    # ------------------------------------------------------------- controls
    def _build_controls(self):
        bar = ttk.Frame(self, style="TFrame")
        bar.pack(fill="x", padx=18, pady=8)

        ttk.Label(bar, text="Universe:", style="Muted.TLabel").pack(side="left")
        uni_default = "S&P 500" if config.universe_source == "sp500" else "Curated (70)"
        self.universe_var = tk.StringVar(value=uni_default)
        cb = ttk.Combobox(bar, textvariable=self.universe_var, width=16, state="readonly",
                          values=["Curated (70)", "S&P 500"])
        cb.pack(side="left", padx=(6, 16))
        cb.bind("<<ComboboxSelected>>", self._on_universe_change)

        ttk.Label(bar, text="Refresh every:", style="Muted.TLabel").pack(side="left")
        self.interval_var = tk.StringVar(value=f"{config.refresh_seconds // 60} min")
        ib = ttk.Combobox(bar, textvariable=self.interval_var, width=9, state="readonly",
                          values=["5 min", "15 min", "30 min", "60 min"])
        ib.pack(side="left", padx=(6, 16))
        ib.bind("<<ComboboxSelected>>", self._on_interval_change)

        self.auto_var = tk.BooleanVar(value=bool(self.prefs.get("auto_refresh", True)))
        ttk.Checkbutton(bar, text="Auto-refresh", variable=self.auto_var,
                        command=self._on_auto_toggle).pack(side="left", padx=(0, 16))

        ttk.Button(bar, text="↻  Refresh now", style="Accent.TButton",
                   command=self._refresh_now).pack(side="left")

        ttk.Label(bar, text="Filter:", style="Muted.TLabel").pack(side="left", padx=(16, 4))
        self.filter_var = tk.StringVar()
        fe = ttk.Combobox(bar, textvariable=self.filter_var, width=10,
                          values=[])  # free-text entry; combobox for consistent styling
        fe.pack(side="left")
        fe.bind("<KeyRelease>", lambda e: self._rerender_all())
        fe.bind("<<ComboboxSelected>>", lambda e: self._rerender_all())
        ttk.Button(bar, text="Export CSV", command=self._export_csv).pack(side="left", padx=(10, 0))

        # Market session + next-refresh indicator (right side).
        self.market_lbl = tk.Label(bar, text="", bg=BG, fg=MUTED, font=("Segoe UI Semibold", 9))
        self.market_lbl.pack(side="right")
        self.updated_lbl = ttk.Label(bar, text="", style="Muted.TLabel")
        self.updated_lbl.pack(side="right", padx=(0, 14))

    # ----------------------------------------------------------------- tabs
    def _build_tabs(self):
        nb = ttk.Notebook(self)
        nb.pack(fill="both", expand=True, padx=18, pady=(4, 6))
        self.nb = nb
        for key, info in HORIZONS.items():
            frame = ttk.Frame(nb, style="TFrame")
            nb.add(frame, text=info["label"])
            tree = self._make_tree(frame, key)
            self.trees[key] = tree
        # Intraday live tab (Phase 2 real-time spine).
        intra = ttk.Frame(nb, style="TFrame")
        nb.add(intra, text="⚡ Intraday")
        self.intraday_tree = self._make_intraday_tree(intra)
        # Alerts tab (Phase 3 alert engine).
        al = ttk.Frame(nb, style="TFrame")
        self._alerts_tab = al
        nb.add(al, text="🔔 Alerts")
        actl = ttk.Frame(al, style="TFrame")
        actl.pack(fill="x", pady=(6, 2))
        ttk.Button(actl, text="＋ New Rule", style="Accent.TButton",
                   command=lambda: self._open_builder("alert")).pack(side="left")
        ttk.Button(actl, text="Manage Rules",
                   command=self._open_manage_rules).pack(side="left", padx=(8, 0))
        self.alert_sound_var = tk.BooleanVar(value=bool(self.prefs.get("alert_sound", True)))
        ttk.Checkbutton(actl, text="🔊 Sound on alert", variable=self.alert_sound_var,
                        command=lambda: userprefs.update(alert_sound=bool(self.alert_sound_var.get()))
                        ).pack(side="left", padx=(12, 0))
        self.alerts_tree = self._make_alerts_tree(al)
        # News tab (Phase 3 news + sentiment).
        nw = ttk.Frame(nb, style="TFrame")
        nb.add(nw, text="📰 News")
        self.news_tree = self._make_news_tree(nw)
        # Scanners tab (Phase 3 real-time scanners).
        sc = ttk.Frame(nb, style="TFrame")
        nb.add(sc, text="🔍 Scanners")
        self.scan_tree = self._make_scanners_tab(sc)

        # Register trees by name for column-width persistence + row menus.
        self._named_trees = {
            "week": self.trees["week"], "month": self.trees["month"],
            "year": self.trees["year"], "intraday": self.intraday_tree,
            "alerts": self.alerts_tree, "news": self.news_tree, "scan": self.scan_tree,
        }
        for tr in self._named_trees.values():
            self._attach_row_menu(tr)

    def _make_scanners_tab(self, parent):
        ctl = ttk.Frame(parent, style="TFrame")
        ctl.pack(fill="x", pady=(6, 2))
        ttk.Label(ctl, text="Scan:", style="Muted.TLabel").pack(side="left")
        avail = scanners_service.available()
        saved = self.prefs.get("scan")
        self.scan_var = tk.StringVar(value=saved if saved in avail else avail[0])
        cb = ttk.Combobox(ctl, textvariable=self.scan_var, width=28, state="readonly",
                          values=avail)
        cb.pack(side="left", padx=(6, 14))
        cb.bind("<<ComboboxSelected>>", lambda e: self._on_scan_change())
        self.scan_combo = cb
        ttk.Button(ctl, text="＋ New Scan", style="Accent.TButton",
                   command=lambda: self._open_builder("scan")).pack(side="left", padx=(4, 8))
        ttk.Button(ctl, text="Delete", command=self._delete_current_scan).pack(side="left", padx=(0, 12))
        self.scan_count_lbl = ttk.Label(ctl, text="", style="Muted.TLabel")
        self.scan_count_lbl.pack(side="left")

        wrap = ttk.Frame(parent, style="TFrame")
        wrap.pack(fill="both", expand=True, pady=4)
        cols = [c[0] for c in SCAN_COLUMNS]
        tree = ttk.Treeview(wrap, columns=cols, show="headings", selectmode="browse")
        for cid, label, width in SCAN_COLUMNS:
            tree.heading(cid, text=label)
            tree.column(cid, width=width, anchor="w" if cid == "ticker" else "e")
        vsb = ttk.Scrollbar(wrap, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=vsb.set)
        tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")
        tree.tag_configure("pos", foreground=GREEN)
        tree.tag_configure("neg", foreground=RED)
        tree.tag_configure("odd", background=PANEL)
        tree.tag_configure("even", background=PANEL2)
        self._attach_sort(tree, SCAN_COLUMNS)
        return tree

    def _make_news_tree(self, parent):
        wrap = ttk.Frame(parent, style="TFrame")
        wrap.pack(fill="both", expand=True, pady=4)
        cols = [c[0] for c in NEWS_COLUMNS]
        tree = ttk.Treeview(wrap, columns=cols, show="headings", selectmode="browse")
        for cid, label, width in NEWS_COLUMNS:
            tree.heading(cid, text=label)
            anchor = "w" if cid in ("ticker", "title", "pub") else "center"
            tree.column(cid, width=width, anchor=anchor, stretch=(cid == "title"))
        vsb = ttk.Scrollbar(wrap, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=vsb.set)
        tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")
        tree.tag_configure("pos", foreground=GREEN)
        tree.tag_configure("neg", foreground=RED)
        tree.tag_configure("neu", foreground=MUTED)
        tree.bind("<Double-1>", self._open_news_link)
        self._news_links = {}
        self._attach_sort(tree, NEWS_COLUMNS)
        return tree

    def _open_news_link(self, _evt=None):
        sel = self.news_tree.selection()
        if sel and sel[0] in self._news_links and self._news_links[sel[0]]:
            webbrowser.open(self._news_links[sel[0]])

    def _make_alerts_tree(self, parent):
        wrap = ttk.Frame(parent, style="TFrame")
        wrap.pack(fill="both", expand=True, pady=4)
        cols = [c[0] for c in ALERT_COLUMNS]
        tree = ttk.Treeview(wrap, columns=cols, show="headings", selectmode="browse")
        for cid, label, width in ALERT_COLUMNS:
            tree.heading(cid, text=label)
            tree.column(cid, width=width, anchor="w", stretch=(cid == "details"))
        vsb = ttk.Scrollbar(wrap, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=vsb.set)
        tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")
        tree.tag_configure("odd", background=PANEL)
        tree.tag_configure("even", background=PANEL2)
        tree.tag_configure("new", foreground=AMBER)
        self._attach_sort(tree, ALERT_COLUMNS)
        return tree

    def _make_intraday_tree(self, parent):
        # Chart panel pinned to the bottom; table fills the rest above it.
        self.intraday_chart_frame = ttk.Frame(parent, style="TFrame", height=180)
        self.intraday_chart_frame.pack(side="bottom", fill="x")
        self.intraday_chart_frame.pack_propagate(False)
        self._intraday_chart_canvas = None
        self._intraday_chart_hint = tk.Label(
            self.intraday_chart_frame, bg=BG, fg=MUTED, font=("Segoe UI", 9),
            text="Select a row to see its intraday chart (price + VWAP).")
        self._intraday_chart_hint.pack(expand=True)

        wrap = ttk.Frame(parent, style="TFrame")
        wrap.pack(side="top", fill="both", expand=True, pady=4)
        cols = [c[0] for c in INTRADAY_COLUMNS]
        tree = ttk.Treeview(wrap, columns=cols, show="headings", selectmode="browse")
        for cid, label, width in INTRADAY_COLUMNS:
            tree.heading(cid, text=label)
            anchor = "w" if cid == "ticker" else "center" if cid in ("orbreak", "ema") else "e"
            tree.column(cid, width=width, anchor=anchor)
        vsb = ttk.Scrollbar(wrap, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=vsb.set)
        tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")
        tree.tag_configure("pos", foreground=GREEN)
        tree.tag_configure("neg", foreground=RED)
        tree.tag_configure("odd", background=PANEL)
        tree.tag_configure("even", background=PANEL2)
        tree.bind("<<TreeviewSelect>>", self._on_intraday_select)
        self._attach_sort(tree, INTRADAY_COLUMNS)
        return tree

    def _on_intraday_select(self, _evt=None):
        sel = self.intraday_tree.selection()
        if not sel or "empty" in self.intraday_tree.item(sel[0])["tags"]:
            return
        ticker = str(self._row_ticker(self.intraday_tree, sel[0])).strip()
        if ticker:
            threading.Thread(target=self._load_intraday_chart, args=(ticker,), daemon=True).start()

    def _load_intraday_chart(self, ticker):
        """Fetch intraday bars (cached briefly) and queue a chart render."""
        try:
            hit = self._intraday_bar_cache.get(ticker)
            if hit and time.time() - hit[0] < 120:
                bars = hit[1]
            else:
                from realtime.feed import get_intraday
                data = get_intraday([ticker], interval="5m", days=2)
                bars = data.get(ticker)
                self._intraday_bar_cache[ticker] = (time.time(), bars)
            self._queue.put(("intraday_chart", (ticker, bars)))
        except Exception as exc:
            self._queue.put(("status", f"Chart fetch failed: {exc}"))

    def _render_intraday_chart(self, ticker, bars):
        frame = self.intraday_chart_frame
        for w in frame.winfo_children():
            w.destroy()
        self._intraday_chart_canvas = None
        try:
            if bars is None or bars.empty:
                tk.Label(frame, text=f"No intraday bars for {ticker}.", bg=BG, fg=MUTED).pack(expand=True)
                return
            import pandas as pd
            from matplotlib.figure import Figure
            from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

            df = bars.sort_index()
            day = df.index[-1].date()
            sess = df[[ts.date() == day for ts in df.index]]
            if len(sess) < 3:
                sess = df.tail(78)
            close = sess["Close"]
            typ = (sess["High"] + sess["Low"] + sess["Close"]) / 3.0
            vol = sess["Volume"].fillna(0)
            vwap = (typ * vol).cumsum() / vol.cumsum().replace(0, pd.NA)
            up = close.iloc[-1] >= close.iloc[0]

            fig = Figure(figsize=(6, 1.7), dpi=100, facecolor="#1a2230")
            ax = fig.add_subplot(111)
            ax.set_facecolor("#1a2230")
            ax.plot(range(len(close)), close.values, color=(GREEN if up else RED), lw=1.5, label=ticker)
            ax.plot(range(len(vwap)), vwap.values, color=ACCENT, lw=1.0, ls="--", label="VWAP")
            ax.fill_between(range(len(close)), close.values, close.min(),
                            color=(GREEN if up else RED), alpha=0.10)
            for s in ax.spines.values():
                s.set_visible(False)
            ax.tick_params(colors="#8b98a9", labelsize=7)
            ax.set_xticks([])
            ax.legend(loc="upper left", fontsize=7, facecolor="#222d3d",
                      edgecolor="none", labelcolor="#e6edf3")
            ax.margins(x=0)
            fig.subplots_adjust(left=0.08, right=0.98, top=0.95, bottom=0.08)
            canvas = FigureCanvasTkAgg(fig, master=frame)
            canvas.draw()
            canvas.get_tk_widget().pack(fill="both", expand=True, padx=8, pady=4)
            self._intraday_chart_canvas = canvas
        except Exception:
            tk.Label(frame, text="Chart unavailable.", bg=BG, fg=MUTED).pack(expand=True)

    # --------------------------------------------------- click-to-sort columns
    def _attach_sort(self, tree, columns):
        for cid, label, _w in columns:
            tree.heading(cid, command=lambda t=tree, c=cid: self._sort_by(t, c))

    def _sort_by(self, tree, col_id):
        cur = self._tree_sort.get(tree)
        desc = not cur[1] if (cur and cur[0] == col_id) else True
        self._tree_sort[tree] = (col_id, desc)
        self._apply_sort(tree)

    def _apply_sort(self, tree):
        s = self._tree_sort.get(tree)
        if not s:
            return
        col_id, desc = s
        try:
            items = [(tree.set(iid, col_id), iid) for iid in tree.get_children("")]
        except Exception:
            return
        items.sort(key=lambda t: _sort_key(t[0]), reverse=desc)
        for idx, (_, iid) in enumerate(items):
            tree.move(iid, "", idx)
        # restripe alternating rows while preserving color tags
        for i, iid in enumerate(tree.get_children("")):
            tags = [t for t in tree.item(iid, "tags") if t not in ("odd", "even")]
            tags.append("even" if i % 2 else "odd")
            tree.item(iid, tags=tags)

    def _make_tree(self, parent, horizon_key):
        wrap = ttk.Frame(parent, style="TFrame")
        wrap.pack(fill="both", expand=True, pady=4)
        cols = [c[0] for c in COLUMNS]
        tree = ttk.Treeview(wrap, columns=cols, show="headings", selectmode="browse")
        for cid, label, width in COLUMNS:
            tree.heading(cid, text=label)
            anchor = "w" if cid in ("ticker", "reasons", "conf") else ("e" if cid in ("est", "price", "band") else "center")
            tree.column(cid, width=width, anchor=anchor, stretch=(cid == "reasons"))
        vsb = ttk.Scrollbar(wrap, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=vsb.set)
        tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")

        tree.tag_configure("pos", foreground=GREEN)
        tree.tag_configure("neg", foreground=RED)
        tree.tag_configure("odd", background=PANEL)
        tree.tag_configure("even", background=PANEL2)
        tree.bind("<Double-1>", lambda e, h=horizon_key: self._show_detail(h))
        self._attach_sort(tree, COLUMNS)
        return tree

    # ------------------------------------------------------------ statusbar
    def _build_statusbar(self):
        bar = ttk.Frame(self, style="TFrame")
        bar.pack(fill="x", side="bottom", padx=18, pady=(0, 10))
        self.status_lbl = ttk.Label(bar, text="", style="Muted.TLabel")
        self.status_lbl.pack(side="left")
        disc = ttk.Label(
            bar,
            text="⚠ Estimates only — not investment advice. Markets are unpredictable; "
                 "do your own research.",
            style="Muted.TLabel",
        )
        disc.pack(side="right")

    # ------------------------------------------------------------- intraday
    def _poll_intraday(self):
        """Refresh the Intraday tab from Redis; self-fetch once if it's empty."""
        try:
            snap = intraday_store.load_latest()
        except Exception:
            snap = {}
        if snap:
            self._render_intraday(snap)
        elif not self._intraday_started:
            # No Celery worker / empty Redis -> do a one-off background fetch.
            self._intraday_started = True
            self._set_status("Fetching first intraday snapshot…")
            threading.Thread(target=self._intraday_fetch_once, daemon=True).start()
        self.after(20000, self._poll_intraday)  # every 20s

    def _intraday_fetch_once(self):
        try:
            from realtime.ingestor import refresh_intraday
            snap = refresh_intraday(progress=lambda m: self._queue.put(("status", m)))
            self._queue.put(("intraday", snap))
        except Exception as exc:
            self._queue.put(("status", f"Intraday fetch failed: {exc}"))

    def _render_intraday(self, snap: dict):
        tree = self.intraday_tree
        tree.delete(*tree.get_children())
        if not snap:
            self._empty_state(tree, len(INTRADAY_COLUMNS), "Fetching intraday data…")
            return
        # sort by absolute move from open (most active first)
        items = sorted(snap.items(), key=lambda kv: abs(kv[1].get("pct_from_open") or 0), reverse=True)
        for i, (ticker, d) in enumerate(items):
            if not self._match_filter(ticker):
                continue
            po = d.get("pct_from_open")
            pv = d.get("pct_from_vwap")
            orbreak = "▲ above" if d.get("above_or_high") else "▼ below" if d.get("below_or_low") else "—"
            ema = "bull ↑" if d.get("ema_stack_bull") else "bear ↓"
            vals = (
                ticker,
                f"${d.get('last'):,.2f}" if d.get("last") is not None else "—",
                f"{po:+.2f}%" if po is not None else "—",
                f"{pv:+.2f}%" if pv is not None else "—",
                f"{d.get('rvol'):.2f}" if d.get("rvol") is not None else "—",
                f"{d.get('rsi14'):.0f}" if d.get("rsi14") is not None else "—",
                f"{d.get('atr14'):.2f}" if d.get("atr14") is not None else "—",
                orbreak, ema, d.get("bars", "—"),
            )
            tag = "pos" if (po or 0) >= 0 else "neg"
            tree.insert("", "end", values=vals, tags=(tag, "even" if i % 2 else "odd"))
        self._finalize(tree, len(INTRADAY_COLUMNS))

    # --------------------------------------------------------------- alerts
    def _poll_alerts(self):
        try:
            fired = storage.recent_fired(limit=100)
        except Exception:
            fired = []
        self._render_alerts(fired)
        # Tab badge with the count of fired alerts.
        try:
            self.nb.tab(self._alerts_tab, text=f"🔔 Alerts ({len(fired)})" if fired else "🔔 Alerts")
        except Exception:
            pass
        if len(fired) > self._alert_seen and self._alert_seen >= 0:
            newest = fired[0] if fired else None
            if newest:
                self._set_status(f"🔔 {newest['ticker']}: {newest['rule_name']}")
                if self._alert_seen > 0:  # don't beep on the initial load
                    self._play_alert_sound()
        self._alert_seen = len(fired)
        self.after(15000, self._poll_alerts)

    def _render_alerts(self, fired: list):
        tree = self.alerts_tree
        tree.delete(*tree.get_children())
        if not fired:
            self._empty_state(tree, len(ALERT_COLUMNS),
                              "No alerts fired yet — add rules with ＋ New Rule.")
            return
        for i, a in enumerate(fired):
            if not self._match_filter(a.get("ticker", "")):
                continue
            t = a.get("fired_at")
            tstr = t.strftime("%H:%M:%S") if hasattr(t, "strftime") else str(t)
            details = (a.get("message") or "")
            if "—" in details:
                details = details.split("—", 1)[1].strip()
            tree.insert("", "end",
                        values=(tstr, a.get("ticker", ""), a.get("rule_name", ""), details),
                        tags=("new" if i == 0 else ("even" if i % 2 else "odd"),))
        self._finalize(tree, len(ALERT_COLUMNS))

    # ----------------------------------------------------------------- news
    def _poll_news(self):
        try:
            headlines = news_service.load_headlines()
        except Exception:
            headlines = {}
        if headlines:
            self._render_news(headlines)
        elif not self._news_started:
            self._news_started = True
            threading.Thread(target=self._news_fetch_once, daemon=True).start()
        self.after(30000, self._poll_news)

    def _news_fetch_once(self):
        try:
            news_service.refresh_news(progress=lambda m: self._queue.put(("status", m)))
            self._queue.put(("news", news_service.load_headlines()))
        except Exception as exc:
            self._queue.put(("status", f"News fetch failed: {exc}"))

    def _render_news(self, headlines: dict):
        tree = self.news_tree
        tree.delete(*tree.get_children())
        self._news_links = {}
        rows = []
        for ticker, items in headlines.items():
            for it in items:
                rows.append((ticker, it))
        # newest first
        rows.sort(key=lambda r: r[1].get("published_at") or "", reverse=True)
        for i, (ticker, it) in enumerate(rows[:200]):
            if not self._match_filter(ticker):
                continue
            sc = it.get("score", 0) or 0
            tag = "pos" if sc > 0.05 else "neg" if sc < -0.05 else "neu"
            arrow = "▲" if sc > 0.05 else "▼" if sc < -0.05 else "•"
            pub_at = (it.get("published_at") or "")[:16].replace("T", " ")
            iid = tree.insert("", "end", values=(
                ticker, f"{arrow} {sc:+.2f}", pub_at,
                it.get("title", ""), it.get("publisher") or "—",
            ), tags=(tag,))
            self._news_links[iid] = it.get("link")
        self._finalize(tree, len(NEWS_COLUMNS))

    # ------------------------------------------------------------- scanners
    def _poll_scanners(self):
        self._run_scan()
        self.after(20000, self._poll_scanners)

    def _run_scan(self):
        try:
            rows = scanners_service.run_named(self.scan_var.get(), limit=60)
        except Exception:
            rows = []
        self.scan_count_lbl.config(text=f"{len(rows)} match(es)")
        tree = self.scan_tree
        tree.delete(*tree.get_children())
        if not rows:
            self._empty_state(tree, len(SCAN_COLUMNS),
                              "No matches — waiting for intraday data or none qualify right now.")
            return
        for i, r in enumerate(rows):
            if not self._match_filter(r.get("ticker", "")):
                continue
            po = r.get("pct_from_open")
            pv = r.get("pct_from_vwap")
            ns = r.get("news_sentiment")
            vals = (
                r.get("ticker", ""),
                f"${r.get('last'):,.2f}" if r.get("last") is not None else "—",
                f"{po:+.2f}%" if po is not None else "—",
                f"{pv:+.2f}%" if pv is not None else "—",
                f"{r.get('rvol'):.2f}" if r.get("rvol") is not None else "—",
                f"{r.get('rsi14'):.0f}" if r.get("rsi14") is not None else "—",
                f"{r.get('atr14'):.2f}" if r.get("atr14") is not None else "—",
                f"{ns:+.2f}" if ns is not None else "—",
            )
            tag = "pos" if (po or 0) >= 0 else "neg"
            tree.insert("", "end", values=vals, tags=(tag, "even" if i % 2 else "odd"))
        self._finalize(tree, len(SCAN_COLUMNS))

    # ------------------------------------------------- rule / scan builder
    def _open_builder(self, kind: str):
        """Modal dialog to build an alert rule (kind='alert') or scan ('scan')."""
        is_alert = kind == "alert"
        win = tk.Toplevel(self)
        win.title("New Alert Rule" if is_alert else "New Scan")
        win.configure(bg=PANEL)
        win.geometry("560x560")
        win.transient(self)
        win.grab_set()
        pad = dict(padx=16, pady=4)

        def lbl(parent, text):
            return tk.Label(parent, text=text, bg=PANEL, fg=MUTED, font=("Segoe UI", 9))

        tk.Label(win, text=("New Alert Rule" if is_alert else "New Scan"),
                 bg=PANEL, fg=ACCENT, font=("Segoe UI Semibold", 15)).pack(anchor="w", **pad)

        top = tk.Frame(win, bg=PANEL)
        top.pack(fill="x", **pad)
        lbl(top, "Name").grid(row=0, column=0, sticky="w")
        name_var = tk.StringVar()
        tk.Entry(top, textvariable=name_var, width=44).grid(row=0, column=1, columnspan=3, sticky="w", padx=6, pady=3)

        scope_var = tk.StringVar(value="*")
        cooldown_var = tk.StringVar(value="1800")
        sort_var = tk.StringVar(value="pct_from_open")
        desc_var = tk.BooleanVar(value=True)
        if is_alert:
            lbl(top, "Scope").grid(row=1, column=0, sticky="w")
            tk.Entry(top, textvariable=scope_var, width=12).grid(row=1, column=1, sticky="w", padx=6)
            lbl(top, "(* = all, or a ticker)").grid(row=1, column=2, sticky="w")
            lbl(top, "Cooldown (s)").grid(row=2, column=0, sticky="w")
            tk.Entry(top, textvariable=cooldown_var, width=12).grid(row=2, column=1, sticky="w", padx=6, pady=3)
        else:
            lbl(top, "Sort by").grid(row=1, column=0, sticky="w")
            ttk.Combobox(top, textvariable=sort_var, width=18, state="readonly",
                         values=[f for f, _, _ in SUPPORTED_FIELDS]).grid(row=1, column=1, sticky="w", padx=6)
            tk.Checkbutton(top, text="Descending", variable=desc_var, bg=PANEL, fg=FG,
                           selectcolor=PANEL2, activebackground=PANEL).grid(row=1, column=2, sticky="w")

        # --- condition adder ---
        tk.Frame(win, bg=PANEL2, height=1).pack(fill="x", padx=16, pady=8)
        lbl(win, "Conditions (all must be true):").pack(anchor="w", padx=16)
        adder = tk.Frame(win, bg=PANEL)
        adder.pack(fill="x", **pad)
        field_labels = [l for _, l, _ in SUPPORTED_FIELDS]
        field_by_label = {l: f for f, l, _ in SUPPORTED_FIELDS}
        kind_by_field = {f: k for f, _, k in SUPPORTED_FIELDS}
        f_var = tk.StringVar(value=field_labels[0])
        op_var = tk.StringVar(value="<")
        val_var = tk.StringVar(value="30")
        fcb = ttk.Combobox(adder, textvariable=f_var, width=22, state="readonly", values=field_labels)
        fcb.grid(row=0, column=0, padx=2)
        opcb = ttk.Combobox(adder, textvariable=op_var, width=13, state="readonly", values=SUPPORTED_OPS)
        opcb.grid(row=0, column=1, padx=2)
        val_entry = tk.Entry(adder, textvariable=val_var, width=10)
        val_entry.grid(row=0, column=2, padx=2)

        def _sync_val_state(*_):
            is_bool = op_var.get() in ("is_true", "is_false")
            val_entry.config(state="disabled" if is_bool else "normal")
        op_var.trace_add("write", _sync_val_state)

        conditions: list[dict] = []
        listbox = tk.Listbox(win, height=8, bg=PANEL2, fg=FG, selectbackground="#2d4a73",
                             borderwidth=0, highlightthickness=0, font=("Consolas", 10))

        def _add_condition():
            field = field_by_label[f_var.get()]
            op = op_var.get()
            if op in ("is_true", "is_false"):
                value = True
            else:
                try:
                    value = float(val_var.get())
                except ValueError:
                    messagebox.showerror("Invalid value", "Enter a number for this operator.", parent=win)
                    return
            conditions.append({"field": field, "op": op, "value": value})
            listbox.insert("end", f"{field}  {op}  {value if op not in ('is_true','is_false') else ''}".rstrip())

        def _remove_condition():
            for i in reversed(listbox.curselection()):
                listbox.delete(i)
                del conditions[i]

        tk.Button(adder, text="Add", command=_add_condition).grid(row=0, column=3, padx=4)
        listbox.pack(fill="both", expand=True, padx=16, pady=(2, 4))
        tk.Button(win, text="Remove selected", command=_remove_condition).pack(anchor="w", padx=16)

        # --- save / cancel ---
        btns = tk.Frame(win, bg=PANEL)
        btns.pack(fill="x", padx=16, pady=12)

        def _save():
            name = name_var.get().strip()
            if not name:
                messagebox.showerror("Missing name", "Give it a name.", parent=win)
                return
            if not conditions:
                messagebox.showerror("No conditions", "Add at least one condition.", parent=win)
                return
            try:
                if is_alert:
                    storage.save_rule(name, conditions, scope=scope_var.get().strip() or "*",
                                      cooldown_sec=int(cooldown_var.get() or 1800))
                    self._poll_alerts()
                else:
                    storage.save_scan(name, conditions, sort=sort_var.get(), desc=desc_var.get())
                    self.scan_combo.config(values=scanners_service.available())
                    self.scan_var.set(name)
                    self._run_scan()
            except Exception as exc:
                messagebox.showerror("Save failed", str(exc), parent=win)
                return
            win.destroy()

        tk.Button(btns, text="Save", command=_save, width=12).pack(side="right")
        tk.Button(btns, text="Cancel", command=win.destroy, width=10).pack(side="right", padx=6)

    def _open_manage_rules(self):
        win = tk.Toplevel(self)
        win.title("Manage Alert Rules")
        win.configure(bg=PANEL)
        win.geometry("640x420")
        win.transient(self)
        win.grab_set()

        cols = ("name", "scope", "enabled", "conds")
        tree = ttk.Treeview(win, columns=cols, show="headings", selectmode="browse")
        for cid, label, w in [("name", "Rule", 320), ("scope", "Scope", 80),
                              ("enabled", "Enabled", 80), ("conds", "Conditions", 120)]:
            tree.heading(cid, text=label)
            tree.column(cid, width=w, anchor="w")
        tree.pack(fill="both", expand=True, padx=12, pady=10)

        id_by_item = {}

        def _reload():
            tree.delete(*tree.get_children())
            id_by_item.clear()
            for r in storage.get_rules(enabled_only=False):
                iid = tree.insert("", "end", values=(
                    r["name"], r["scope"], "yes" if r["enabled"] else "no", len(r["conditions"])))
                id_by_item[iid] = r["id"]

        def _toggle():
            sel = tree.selection()
            if not sel:
                return
            rid = id_by_item[sel[0]]
            cur = tree.item(sel[0])["values"][2] == "yes"
            storage.set_rule_enabled(rid, not cur)
            _reload()

        def _delete():
            sel = tree.selection()
            if not sel:
                return
            if messagebox.askyesno("Delete rule", "Delete the selected rule?", parent=win):
                storage.delete_rule(id_by_item[sel[0]])
                _reload()

        btns = tk.Frame(win, bg=PANEL)
        btns.pack(fill="x", padx=12, pady=(0, 12))
        tk.Button(btns, text="Enable / Disable", command=_toggle).pack(side="left")
        tk.Button(btns, text="Delete", command=_delete).pack(side="left", padx=8)
        tk.Button(btns, text="Close", command=win.destroy).pack(side="right")
        _reload()

    def _delete_current_scan(self):
        name = self.scan_var.get()
        from scanners.library import SCANS_BY_NAME
        if name in SCANS_BY_NAME:
            messagebox.showinfo("Built-in scan", "Built-in scans can't be deleted.", parent=self)
            return
        if messagebox.askyesno("Delete scan", f"Delete custom scan '{name}'?", parent=self):
            storage.delete_scan(name)
            vals = scanners_service.available()
            self.scan_combo.config(values=vals)
            self.scan_var.set(vals[0])
            self._run_scan()

    # ------------------------------------------------------------- handlers
    def _on_universe_change(self, _evt=None):
        config.universe_source = "sp500" if self.universe_var.get().startswith("S&P") else "watchlist"
        userprefs.update(universe_source=config.universe_source)
        self._set_status("Universe changed — refreshing…")
        self.agg.refresh_now()

    def _on_interval_change(self, _evt=None):
        mins = int(self.interval_var.get().split()[0])
        config.refresh_seconds = mins * 60
        userprefs.update(refresh_seconds=config.refresh_seconds)

    def _on_auto_toggle(self):
        userprefs.update(auto_refresh=bool(self.auto_var.get()))

    def _on_scan_change(self):
        userprefs.update(scan=self.scan_var.get())
        self._run_scan()

    def _refresh_now(self):
        self._set_status("Manual refresh requested…")
        self.agg.refresh_now()

    # ----------------------------------------------------- filter / export
    def _match_filter(self, ticker) -> bool:
        f = self.filter_var.get().strip().upper()
        return (not f) or (f in str(ticker).upper())

    def _rerender_all(self):
        """Re-render every tab from its current source (used on filter change)."""
        if self.results:
            self._render(self.results)
        try:
            self._render_intraday(intraday_store.load_latest())
        except Exception:
            pass
        try:
            self._render_news(news_service.load_headlines())
        except Exception:
            pass
        try:
            self._run_scan()
        except Exception:
            pass
        try:
            self._render_alerts(storage.recent_fired(limit=100))
        except Exception:
            pass

    def _finalize(self, tree, ncols):
        """After populating: show a placeholder if empty, else apply the sort."""
        if not tree.get_children(""):
            msg = "No rows match the filter." if self.filter_var.get().strip() else "No data yet."
            self._empty_state(tree, ncols, msg)
        else:
            self._apply_sort(tree)

    def _active_tree(self):
        order = [self.trees["week"], self.trees["month"], self.trees["year"],
                 self.intraday_tree, self.alerts_tree, self.news_tree, self.scan_tree]
        try:
            idx = self.nb.index("current")
            return order[idx] if 0 <= idx < len(order) else None
        except Exception:
            return None

    def _export_csv(self):
        tree = self._active_tree()
        if not tree:
            return
        cols = tree["columns"]
        headers = [tree.heading(c).get("text", c) for c in cols]
        rows = [tree.item(i)["values"] for i in tree.get_children("")
                if "empty" not in tree.item(i)["tags"]]
        if not rows:
            messagebox.showinfo("Export CSV", "Nothing to export on this tab.", parent=self)
            return
        path = filedialog.asksaveasfilename(
            defaultextension=".csv", filetypes=[("CSV files", "*.csv")],
            initialfile="stockpredict_export.csv", parent=self)
        if not path:
            return
        try:
            with open(path, "w", newline="", encoding="utf-8") as fh:
                w = csv.writer(fh)
                w.writerow(headers)
                w.writerows(rows)
            self._set_status(f"Exported {len(rows)} rows → {path}")
        except Exception as exc:
            messagebox.showerror("Export failed", str(exc), parent=self)

    # ------------------------------------------------ right-click row menu
    def _attach_row_menu(self, tree):
        tree.bind("<Button-3>", lambda e, t=tree: self._on_row_right_click(e, t))

    def _row_ticker(self, tree, iid):
        cols = tree["columns"]
        if "ticker" in cols:
            return tree.set(iid, "ticker")
        return tree.item(iid)["values"][1] if len(tree.item(iid)["values"]) > 1 else ""

    def _on_row_right_click(self, event, tree):
        iid = tree.identify_row(event.y)
        if not iid or "empty" in tree.item(iid)["tags"]:
            return
        tree.selection_set(iid)
        ticker = str(self._row_ticker(tree, iid)).strip()
        if not ticker:
            return
        menu = tk.Menu(self, tearoff=0, bg=PANEL2, fg=FG,
                       activebackground="#2d4a73", activeforeground=FG)
        menu.add_command(label=f"Copy “{ticker}”", command=lambda: self._copy_text(ticker))
        menu.add_command(label="Open in Yahoo Finance",
                         command=lambda: webbrowser.open(f"https://finance.yahoo.com/quote/{ticker}"))
        menu.add_separator()
        menu.add_command(label="New alert for this ticker…",
                         command=lambda: self._open_builder("alert"))
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    def _copy_text(self, text):
        try:
            self.clipboard_clear()
            self.clipboard_append(text)
            self._set_status(f"Copied “{text}” to clipboard")
        except Exception:
            pass

    # ----------------------------------------------------- column widths
    def _restore_col_widths(self):
        saved = self.prefs.get("col_widths", {})
        for name, tree in self._named_trees.items():
            widths = saved.get(name, {})
            for cid, w in widths.items():
                try:
                    tree.column(cid, width=int(w))
                except Exception:
                    pass

    def _collect_col_widths(self) -> dict:
        out = {}
        for name, tree in self._named_trees.items():
            try:
                out[name] = {cid: tree.column(cid, "width") for cid in tree["columns"]}
            except Exception:
                pass
        return out

    # ------------------------------------------------------- alert sound
    def _play_alert_sound(self):
        if not getattr(self, "alert_sound_var", None) or not self.alert_sound_var.get():
            return
        def _beep():
            try:
                import winsound
                winsound.MessageBeep(winsound.MB_ICONASTERISK)
            except Exception:
                try:
                    self.bell()
                except Exception:
                    pass
        threading.Thread(target=_beep, daemon=True).start()

    def _tick(self):
        """1 Hz: market session label + countdown to the next scheduled refresh."""
        try:
            label, hint = market.status()
            color = {"green": GREEN, "amber": AMBER, "muted": MUTED}.get(hint, MUTED)
            countdown = ""
            if self.auto_var.get() and self._last_refresh_ts:
                remaining = int(self._last_refresh_ts + config.refresh_seconds - time.time())
                if remaining > 0:
                    countdown = f"  ·  next in {remaining // 60}m {remaining % 60:02d}s"
            self.market_lbl.config(text=f"● {label}{countdown}", fg=color)
        except Exception:
            pass
        self.after(1000, self._tick)

    def _drain_queue(self):
        try:
            while True:
                kind, payload = self._queue.get_nowait()
                if kind == "status":
                    self._set_status(payload)
                elif kind == "intraday":
                    if payload:
                        self._render_intraday(payload)
                elif kind == "intraday_chart":
                    ticker, bars = payload
                    self._render_intraday_chart(ticker, bars)
                elif kind == "news":
                    if payload:
                        self._render_news(payload)
                elif kind == "update":
                    results, meta = payload
                    self.results, self.meta = results, meta
                    self._last_refresh_ts = time.time()
                    self._render(results)
                    self.updated_lbl.config(
                        text=f"Updated {meta['updated_at']:%H:%M:%S}  ·  "
                             f"{meta['priced']} priced  ·  {meta['with_fundamentals']} fundamentals")
        except queue.Empty:
            pass
        # Honor the auto-refresh toggle by suspending the loop's wake cadence.
        self.after(200, self._drain_queue)

    def _render(self, results):
        for key, tree in self.trees.items():
            tree.delete(*tree.get_children())
            df = results.get(key)
            if df is None or df.empty:
                self._empty_state(tree, len(COLUMNS), "Waiting for the first screen…")
                continue
            for i, (_, row) in enumerate(df.head(config.top_n).iterrows()):
                if not self._match_filter(row["ticker"]):
                    continue
                est = row["est_return"]
                tag_sign = "pos" if est >= 0 else "neg"
                band = f"{row['band_lo']*100:+.1f}%  …  {row['band_hi']*100:+.1f}%"
                conf = row["confidence"]
                conf_str = self._conf_bar(conf)
                price = f"${row['price']:,.2f}" if row["price"] and row["price"] == row["price"] else "—"
                vals = (
                    int(row.name) if hasattr(row, "name") else i + 1,
                    row["ticker"],
                    f"{est*100:+.1f}%",
                    band,
                    conf_str,
                    price,
                    row["reasons"],
                )
                stripe = "even" if i % 2 else "odd"
                tree.insert("", "end", values=vals, tags=(tag_sign, stripe))
            self._finalize(tree, len(COLUMNS))

    def _empty_state(self, tree, ncols, text):
        """Show a single muted placeholder row when a table has no data."""
        vals = [""] * ncols
        vals[1 if ncols > 1 else 0] = text
        tree.insert("", "end", values=vals, tags=("empty",))
        tree.tag_configure("empty", foreground=MUTED)

    @staticmethod
    def _conf_bar(conf):
        filled = int(round(conf / 100 * 10))
        return f"{'█' * filled}{'░' * (10 - filled)} {conf:.0f}%"

    def _show_detail(self, horizon_key):
        tree = self.trees[horizon_key]
        sel = tree.selection()
        if not sel or self.results is None:
            return
        ticker = tree.item(sel[0])["values"][1]
        df = self.results.get(horizon_key)
        if df is None or df.empty:
            return
        row = df[df["ticker"] == ticker]
        if row.empty:
            return
        r = row.iloc[0]

        win = tk.Toplevel(self)
        win.title(f"{ticker} — {HORIZONS[horizon_key]['label']}")
        win.configure(bg=PANEL)
        win.geometry("470x640")
        pad = {"padx": 18, "pady": 4}

        tk.Label(win, text=ticker, bg=PANEL, fg=ACCENT,
                 font=("Segoe UI Semibold", 18)).pack(anchor="w", **pad)
        tk.Label(win, text=f"{HORIZONS[horizon_key]['label']} estimate",
                 bg=PANEL, fg=MUTED, font=("Segoe UI", 10)).pack(anchor="w", padx=18)

        def line(k, v, color=FG):
            f = tk.Frame(win, bg=PANEL)
            f.pack(fill="x", padx=18, pady=2)
            tk.Label(f, text=k, bg=PANEL, fg=MUTED, font=("Segoe UI", 10), width=22, anchor="w").pack(side="left")
            tk.Label(f, text=v, bg=PANEL, fg=color, font=("Segoe UI Semibold", 10), anchor="w").pack(side="left")

        est = r["est_return"]
        line("Estimated return", f"{est*100:+.2f}%", GREEN if est >= 0 else RED)
        line("Plausible range (±1σ)", f"{r['band_lo']*100:+.1f}%  …  {r['band_hi']*100:+.1f}%")
        line("Confidence", f"{r['confidence']:.0f}%  (data + signal strength)")
        line("Composite signal (z)", f"{r['signal_z']:+.2f}")
        line("Current price", f"${r['price']:,.2f}" if r['price'] == r['price'] else "—")
        line("Annualized volatility", f"{r['vol_ann']*100:.0f}%" if r['vol_ann'] == r['vol_ann'] else "—")
        tk.Frame(win, bg=PANEL2, height=1).pack(fill="x", padx=18, pady=8)
        line("Return 1 week", _pct(r['ret_5']))
        line("Return 1 month", _pct(r['ret_21']))
        line("Return 3 month", _pct(r['ret_63']))
        line("Return 12 month", _pct(r['ret_252']))
        line("12-1 momentum", _pct(r['mom_12_1']))
        line("Quality/value (0-1)", f"{r['quality_value']:.2f}" if r['quality_value'] == r['quality_value'] else "n/a")
        line("Vs. 52-week high", _pct(r['dist_52w_high']))

        self._add_sparkline(win, ticker)

        tk.Frame(win, bg=PANEL2, height=1).pack(fill="x", padx=18, pady=8)
        btns = tk.Frame(win, bg=PANEL)
        btns.pack(fill="x", padx=18, pady=6)
        tk.Button(btns, text="Open Yahoo Finance",
                  command=lambda: webbrowser.open(f"https://finance.yahoo.com/quote/{ticker}")
                  ).pack(side="left")
        tk.Button(btns, text="Close", command=win.destroy).pack(side="right")

    def _add_sparkline(self, win, ticker, days=120):
        """Embed a small price chart from the cached daily prices (no network)."""
        try:
            from stockpredict.data import _load_cached_prices
            prices = _load_cached_prices()
            if prices is None or prices.empty or ticker not in prices.columns:
                return
            series = prices[ticker].dropna().tail(days)
            if len(series) < 5:
                return
            import matplotlib
            matplotlib.use("Agg")
            from matplotlib.figure import Figure
            from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

            up = series.iloc[-1] >= series.iloc[0]
            fig = Figure(figsize=(4.2, 1.4), dpi=100, facecolor="#1a2230")
            ax = fig.add_subplot(111)
            ax.set_facecolor("#1a2230")
            ax.plot(series.index, series.values, color=(GREEN if up else RED), lw=1.6)
            ax.fill_between(series.index, series.values, series.min(),
                            color=(GREEN if up else RED), alpha=0.12)
            for s in ax.spines.values():
                s.set_visible(False)
            ax.tick_params(colors="#8b98a9", labelsize=7)
            ax.margins(x=0)
            fig.subplots_adjust(left=0.12, right=0.98, top=0.92, bottom=0.18)
            tk.Label(win, text=f"Price — last {len(series)} sessions",
                     bg=PANEL, fg=MUTED, font=("Segoe UI", 9)).pack(anchor="w", padx=18, pady=(8, 0))
            canvas = FigureCanvasTkAgg(fig, master=win)
            canvas.draw()
            canvas.get_tk_widget().pack(fill="x", padx=16, pady=2)
        except Exception:
            pass  # sparkline is a nice-to-have; never break the dialog

    # -------------------------------------------------------------- helpers
    def _set_status(self, msg):
        self.status_lbl.config(text=msg)

    def _on_close(self):
        try:
            userprefs.update(
                geometry=self.geometry(),
                universe_source=config.universe_source,
                refresh_seconds=config.refresh_seconds,
                auto_refresh=bool(self.auto_var.get()),
                scan=self.scan_var.get(),
                alert_sound=bool(self.alert_sound_var.get()),
                col_widths=self._collect_col_widths(),
            )
        except Exception:
            pass
        try:
            self.agg.stop()
        except Exception:
            pass
        self.destroy()


def _sort_key(text):
    """Coerce a displayed cell to a sort key: numbers sort numerically, else text.

    Handles values like '+3.6%', '$1,061.25', '███ 70%', '▲ +0.50', '—'.
    """
    if text is None:
        return (1, "")
    s = str(text)
    m = re.search(r"-?\d[\d,]*\.?\d*", s.replace(",", ""))
    if m:
        try:
            return (0, float(m.group()))
        except ValueError:
            pass
    return (1, s.lower())


def _pct(x):
    try:
        if x != x:  # NaN
            return "n/a"
        return f"{x*100:+.1f}%"
    except Exception:
        return "n/a"


def _setup_logging():
    """Log to a rotating file in the data dir; also install a global excepthook."""
    import logging
    from logging.handlers import RotatingFileHandler
    from stockpredict.config import CACHE_DIR

    log_dir = CACHE_DIR / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(log_dir / "stockpredict.log", maxBytes=1_000_000, backupCount=3, encoding="utf-8")
    logging.basicConfig(level=logging.INFO, handlers=[handler],
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    return logging.getLogger("stockpredict.app"), log_dir


def _selftest() -> int:
    """Headless import + pipeline smoke test — used to verify a frozen build."""
    import stockpredict.storage as storage
    import stockpredict.model as model      # noqa: F401
    import backtest.engine as bt            # noqa: F401
    import realtime.indicators as ind       # noqa: F401
    import news.sentiment as sent
    import scanners.engine as scan          # noqa: F401
    import matplotlib                       # noqa: F401
    import pandas, numpy                    # noqa: F401
    storage.init_db()
    assert sent.score_text("beats record profit")["score"] > 0
    print(f"stockpredict selftest OK (v{__import__('stockpredict').__version__})")
    return 0


if __name__ == "__main__":
    import sys

    if "--version" in sys.argv:
        print(__import__("stockpredict").__version__)
        sys.exit(0)
    if "--selftest" in sys.argv:
        sys.exit(_selftest())

    log, log_dir = _setup_logging()
    log.info("stockpredict starting")

    def _excepthook(exc_type, exc, tb):
        log.error("Uncaught exception", exc_info=(exc_type, exc, tb))
        try:
            from tkinter import messagebox
            messagebox.showerror(
                "stockpredict error",
                f"An unexpected error occurred:\n\n{exc}\n\nSee the log:\n{log_dir / 'stockpredict.log'}")
        except Exception:
            pass

    sys.excepthook = _excepthook
    try:
        App().mainloop()
    except Exception:
        log.exception("Fatal error in mainloop")
        raise
