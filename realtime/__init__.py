"""Real-time intraday spine (Phase 2, Increment 1).

A pluggable intraday feed -> indicator computation -> Redis snapshot/stream, driven
by Celery in the background so the desktop window always shows current intraday
research. yfinance is the zero-setup prototype provider; the interface is built to
swap in Alpaca/Polygon (true streaming) without touching the consumers.
"""
