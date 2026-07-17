# Packaging stockpredict as a standalone Windows app

The desktop app runs **fully in-process** (SQLite + a threaded aggregator), so the
packaged build needs no Redis or Celery — those stay an optional "power mode" for
always-on scheduled background runs.

## Build

```powershell
pip install -r requirements.txt pyinstaller

# One-file exe -> dist\stockpredict.exe  (single file; slower first start)
pyinstaller --clean --noconfirm stockpredict.spec

# One-folder build -> dist\stockpredict\stockpredict.exe  (faster start, ships a folder)
$env:STOCKPREDICT_ONEDIR = "1"; pyinstaller --clean --noconfirm stockpredict.spec
```

Verify the frozen build without launching the GUI:

```powershell
dist\stockpredict.exe --selftest     # imports pandas/matplotlib/yfinance/sqlalchemy, runs a smoke check
dist\stockpredict.exe --version
```

## What the build does
- Bundles Python + Tk + pandas/numpy/matplotlib/yfinance/SQLAlchemy into the exe.
- Excludes Celery/Kombu and Qt/IPython to keep size down (GUI doesn't use them).
- Data (SQLite DB, prefs, logs, price cache, reports) is written to a per-user
  writable dir — **`%LOCALAPPDATA%\stockpredict`** — never next to the exe.
- A global exception hook logs uncaught errors to
  `%LOCALAPPDATA%\stockpredict\logs\stockpredict.log` and shows a friendly dialog.

## One-file vs one-folder
| | One-file (`stockpredict.exe`) | One-folder (`stockpredict\`) |
|---|---|---|
| Distribution | single file | a folder (zip it) |
| First launch | slower (unpacks to temp) | fast |
| Size | ~ same total | ~ same total |
| Best for | quick sharing | installers / frequent use |

## Still to do before public distribution
1. **Code signing.** Unsigned exes trigger Windows SmartScreen ("unknown publisher").
   Sign with an EV/OV code-signing certificate (`signtool sign /fd sha256 ...`).
2. **App icon.** Add `icon="stockpredict.ico"` to the `EXE(...)` in `stockpredict.spec`.
3. **Installer** (optional). Wrap the one-folder build with Inno Setup / NSIS for a
   Start-menu shortcut and uninstaller.
4. **Auto-update** (optional). Ship a "check for updates" that points at GitHub Releases.
5. **CI.** A GitHub Action that builds on tag and attaches the exe to the Release.

## Optional power mode (Redis + Celery)
Not bundled. Run from source when you want scheduled pre-market screens, intraday
refresh, and weekly backtests (see the main README "Background pipeline" section).
