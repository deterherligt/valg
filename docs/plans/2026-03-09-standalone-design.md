# Standalone Dashboard Design

**Date:** 2026-03-09

## Goal

A self-contained, double-click executable that non-technical users can download and run on macOS or Windows. Fetches election data from the public `valg-data` GitHub repo, serves a local web dashboard, and auto-refreshes every 60 seconds.

---

## Architecture

A single `valg/server.py` starts a Flask server on `localhost:5000` and opens the default browser automatically. The HTML page is embedded as a string inside the Python file — no external assets, nothing that can go missing when bundled.

```
valg-data GitHub repo (public)
        ↓  (HTTP, every 60s)
  background thread (fetcher)
        ↓
    valg.db (SQLite, local)
        ↓
  Flask server (localhost:5000)
        ↓
  browser (auto-opened on start)
```

**Routes:**
- `GET /` — serves the embedded HTML page
- `POST /run` — executes a CLI function, returns plain text output
- `GET /csv/<command>` — returns CSV download for tabular commands

**Background thread:** calls the existing sync logic (HTTP download from `valg-data` GitHub repo, not SFTP) every 60 seconds. Records last-sync timestamp exposed via `GET /sync-status`.

**Data source:** pulls raw JSON files from `https://raw.githubusercontent.com/deterherligt/valg-data/main/` — no SFTP, no credentials, no git CLI required.

---

## UI Layout

Single page, three zones:

```
┌─────────────────────────────────────────────────────────┐
│  valg  •  Syncing every 60s  •  Last sync: 21:34:12     │
├─────────────────────────────────────────────────────────┤
│  [Status] [Flip] [Party: __] [Candidate: __] [Kreds: __]│
│  [Feed] [Commentary]                                     │
├─────────────────────────────────────────────────────────┤
│  [Download CSV]   (only for tabular commands)            │
│                                                          │
│  ┌───────────────────────────────────────────────────┐  │
│  │ Party   Votes        Seats                        │  │
│  │ A       123,456      42                           │  │
│  │ ...                                               │  │
│  └───────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────┘
```

- Monospace `<pre>` output panel, full-width, selectable text
- Active button stays highlighted
- "Download CSV" button only shown for: Status, Flip, Party, Kreds
- Last-sync timestamp updates automatically via JS polling `GET /sync-status`
- When a background sync completes, the current view auto-refreshes

---

## Data fetcher (HTTP, not SFTP)

The standalone tool cannot use SFTP (no server, no credentials). Instead it fetches the already-processed JSON files from the public `valg-data` GitHub repo via HTTPS.

A new `valg/http_fetcher.py` module:
- Lists files via GitHub raw URLs or the GitHub Contents API
- Downloads only changed files (using ETags or `Last-Modified` headers)
- Writes to a local `data/` directory alongside the DB
- Processes via existing `processor.py` + plugins

No git, no GitHub token required — the data repo is public.

---

## CSV export

For tabular commands (status, flip, party, kreds), `GET /csv/<command>` re-runs the query and returns a `.csv` file. The CLI functions are refactored to return structured data (list of dicts) that the server can render as either plain text or CSV.

---

## Distribution

**Build:** GitHub Actions runs PyInstaller on push to `main`:
- macOS runner → `valg-macos` (single binary, `--onefile`)
- Windows runner → `valg-windows.exe` (single binary, `--noconsole --onefile`)

**Release:** both artifacts uploaded to GitHub Releases automatically.

**User flow:**
1. Go to GitHub Releases page
2. Download `valg-macos` or `valg-windows.exe`
3. macOS: right-click → Open (one-time Gatekeeper bypass)
   Windows: More info → Run anyway (one-time SmartScreen bypass)
4. Browser opens automatically at `localhost:5000`

**Executable behaviour:**
- Starts Flask silently (no visible terminal window on Windows via `--noconsole`)
- Opens browser automatically
- Runs until process is killed (Ctrl+C or close terminal on macOS)

---

## Key constraints

- No Python required on user machine
- No internet connection required after first sync (works offline with cached data)
- No configuration — sensible defaults, data stored next to the executable
- Single file download per platform
- macOS: universal binary (arm64 + x86_64) if PyInstaller supports it at build time
