# Scalingo Deployment Design

**Date:** 2026-03-21

## Overview

Deploy the valg Flask dashboard to Scalingo (French PaaS, `<appname>.scalingo.io`). The server does an initial sync on startup, then polls GitHub every 60 seconds for new election data. An admin API protected by a secret token enables runtime control (starting/stopping demo mode) without any UI access.

## Platform

- **Provider:** Scalingo (Scalingo SAS, Strasbourg, France)
- **Subdomain:** `<appname>.scalingo.io` (TLS included)
- **Container size:** S (256 MB RAM)
- **Cost:** ~€7.20/mo; 30-day free trial (no credit card)
- **Filesystem:** Ephemeral — acceptable because `valg.db` is fully derived from downloaded data files and rebuilt on every start

## How the existing sync mechanism works (unchanged)

`_sync_loop` in `server.py` already handles GitHub polling correctly:
- Calls `sync_from_github(data_dir)` from `http_fetcher.py` — uses stdlib `urllib`, no git binary required
- SHA-based change detection: downloads only changed JSON files to `data/`
- On changes: `process_directory(conn, data_dir)` rebuilds `valg.db`

This mechanism works on Scalingo without modification. The only gap is that it currently sleeps before the first sync — the initial load must happen synchronously before binding.

## Data Flow

```
GitHub (valg-data, public repo)
  ↓  sync_from_github() — stdlib urllib, SHA cache, downloads changed JSON to data/
data/ (in-container, ephemeral)
  ↓  process_directory(conn, data_dir)
valg.db (in-container, ephemeral, rebuilt from scratch on startup + on each change)
  ↓
Flask app → /api/* → browser
```

## Code Changes

### `pyproject.toml`
Move `flask` from `optional-dependencies.standalone` to `project.dependencies`.

### `server.py` — `main()` function

Six targeted changes, in order:

**1. Remove `webbrowser.open` call** (line 296 — crashes headlessly on Scalingo):
```python
# Remove this line entirely:
threading.Timer(1.0, lambda: webbrowser.open(f"http://localhost:{args.port}")).start()
```

**2. Bind to `0.0.0.0` and respect `PORT` env var** (line 303):
```python
# Before:
app.run(host="127.0.0.1", port=args.port)
# After:
app.run(host="0.0.0.0", port=int(os.environ.get("PORT", args.port)))
```

**3. Always instantiate `DemoRunner`** (lines 288–291 — remove the `--demo` guard):
```python
# Before:
demo_runner = None
if args.demo:
    from valg.demo import DemoRunner
    demo_runner = DemoRunner()
# After:
from valg.demo import DemoRunner
demo_runner = DemoRunner()
```
The existing `create_app` registers `/demo/state` and `/demo/control` when `demo_runner is not None`. With this change those routes are always registered and the disabled stubs are dead code (no behaviour change — the runner starts in `idle` state, not running).

**4. Initialize demo data_repo as a git repo** (after `data_repo` is resolved, before app start):

On Scalingo, `VALG_DATA_REPO` must be a writable path that is (or becomes) a git repo, because `DemoRunner._run` calls `commit_data_repo()` (local `git add -A` + `git commit`, no push). Add startup logic:
```python
import subprocess
data_repo.mkdir(parents=True, exist_ok=True)
if not (data_repo / ".git").exists():
    subprocess.run(["git", "init"], cwd=str(data_repo), check=True)
    subprocess.run(["git", "config", "user.email", "valg@localhost"], cwd=str(data_repo), check=True)
    subprocess.run(["git", "config", "user.name", "valg"], cwd=str(data_repo), check=True)
```
Set `VALG_DATA_REPO=/tmp/valg-demo-data` on Scalingo. Local dev continues to use the default `../valg-data`.

**5. Initial synchronous sync before binding**:
```python
# After load_plugins(), before create_app():
from valg.http_fetcher import sync_from_github
from valg.models import get_connection, init_db
from valg.processor import process_directory

sync_from_github(data_dir)
_init_conn = get_connection(db_path)
init_db(_init_conn)
process_directory(_init_conn, data_dir)
_init_conn.close()
```
`main()` does not currently open a connection — connections are per-request inside `create_app`. This opens a dedicated connection for the initial build and closes it immediately. `create_app` then opens per-request connections independently; SQLite WAL mode handles the concurrent access.

Scalingo routes traffic only after the process binds. Binding is deferred until initial data is loaded, so the first request always hits a populated DB.

**6. Add admin endpoints** (see Admin API section below — new `@app.route` blocks added directly in `main()` after `create_app`, before `app.run()`):

### `Procfile` (new file)
```
web: python -m valg.server
```

### `.env.example`
Add a commented line showing the Scalingo form:
```
# On Scalingo, use a writable local path (git will be initialised automatically):
# VALG_DATA_REPO=/tmp/valg-demo-data
```

## Admin API

New endpoints added to `server.py`. They supplement the existing `/demo/state` and `/demo/control` (used by the UI); the admin endpoints are the operator's interface, not the browser's.

| Method | Path | Body | Action |
|--------|------|------|--------|
| `POST` | `/admin/demo` | `{"scenario": "kv2025"}` | `demo_runner.set_scenario(name)` then `demo_runner.start(db_path, data_repo)` |
| `POST` | `/admin/demo/stop` | — | `demo_runner.pause()` |

**Auth:** `Authorization: Bearer <token>` on every request. Token read from `VALG_ADMIN_TOKEN` env var at request time (not cached — rotation takes effect immediately without restart). If `VALG_ADMIN_TOKEN` is unset, all `/admin/*` requests return `503 Service Unavailable`.

**Error responses:**
- `503` — `VALG_ADMIN_TOKEN` not configured
- `401` — token missing or wrong (identical response, no oracle)
- `400` — unknown scenario name
- `200` — action applied

**Usage:**
```bash
curl -X POST https://<appname>.scalingo.io/admin/demo \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"scenario": "kv2025"}'

curl -X POST https://<appname>.scalingo.io/admin/demo/stop \
  -H "Authorization: Bearer <token>"
```

## Environment Variables

Set in Scalingo dashboard or via Scalingo CLI. Never stored in any file.

| Variable | Required | Description |
|----------|----------|-------------|
| `VALG_ADMIN_TOKEN` | Yes | Admin API secret. Generate: `openssl rand -hex 32` |
| `VALG_DATA_REPO` | Yes | Local writable path for demo data repo: `/tmp/valg-demo-data` |
| `VALG_AI_API_KEY` | No | Enables AI commentary. Omit to disable. |
| `VALG_AI_MODEL` | No | Defaults to `claude-sonnet-4-6` |

`VALG_SFTP_*` vars are not needed. `sync_from_github` has `REPO = "deterherligt/valg-data"` hardcoded in `http_fetcher.py` — no configuration needed for the GitHub sync path.

## What Does Not Change

- `_sync_loop` and `http_fetcher.sync_from_github` — the existing polling mechanism works unchanged
- All `/api/*` endpoints
- `/demo/state` and `/demo/control` (UI-facing demo controls)
- Flask templates and static assets
- Demo engine (`valg/demo.py`, `valg/scenarios/`)
- CLI (`valg/cli.py`)
- GitHub Actions sync workflow (`sync.yml`)
- SQLite schema and plugins

## Security Notes

- Admin token never written to any file or committed to any repo
- Token read from env at request time — rotation requires no restart
- `401` is identical for missing and wrong tokens (no oracle)
- `503` if token env var is unset — fails loud rather than silent open access
- Dashboard remains fully public (read-only API, no write surface)
- SFTP credentials are not present on the server

## Out of Scope

- Custom domain (`.dk`) — add later via Scalingo domain settings
- PWA / "Add to Home Screen" — separate task
- Response caching for `/api/parties` D'Hondt calculations — separate task
