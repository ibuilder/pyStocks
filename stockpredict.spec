# PyInstaller build spec for the stockpredict desktop app.
#   pyinstaller stockpredict.spec          -> dist/stockpredict.exe (one file)
#   set STOCKPREDICT_ONEDIR=1 first         -> dist/stockpredict/ (folder, faster start)
#
# The GUI runs fully in-process (SQLite + threaded aggregator); Celery/Redis are an
# optional power-mode and are intentionally excluded from this bundle.
import os
from PyInstaller.utils.hooks import collect_all, collect_submodules

datas, binaries, hiddenimports = [], [], []

# yfinance ships data files and pulls a few dynamically-imported deps.
for pkg in ("yfinance",):
    d, b, h = collect_all(pkg)
    datas += d
    binaries += b
    hiddenimports += h

hiddenimports += collect_submodules("sqlalchemy")
hiddenimports += [
    "matplotlib.backends.backend_tkagg",
    "winotify",
    "redis",
    "bs4",
]

excludes = [
    "celery", "kombu", "billiard", "amqp", "vine",   # optional power-mode only
    "PyQt5", "PyQt6", "PySide2", "PySide6",
    "IPython", "notebook", "pytest", "tornado",
]

a = Analysis(
    ["app.py"],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
)
pyz = PYZ(a.pure)

ONEDIR = os.environ.get("STOCKPREDICT_ONEDIR") == "1"
ICON = "stockpredict.ico" if os.path.exists("stockpredict.ico") else None

if ONEDIR:
    exe = EXE(pyz, a.scripts, [], exclude_binaries=True,
              name="stockpredict", console=False, icon=ICON,
              disable_windowed_traceback=False)
    coll = COLLECT(exe, a.binaries, a.datas, name="stockpredict")
else:
    exe = EXE(pyz, a.scripts, a.binaries, a.datas, [],
              name="stockpredict", console=False, icon=ICON,
              upx=False, disable_windowed_traceback=False)
