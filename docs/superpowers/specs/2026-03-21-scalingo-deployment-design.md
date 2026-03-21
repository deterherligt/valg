# Scalingo Deployment Design

**Date:** 2026-03-21
**Status:** Approved

## Overview

Deploy the valg Flask dashboard to Scalingo (French PaaS, `valg.scalingo.io`). The server clones the public `valg-data` repo on startup, builds `valg.db`, and polls GitHub every 60 seconds for new commits — rebuilding the DB when data changes. An admin API protected by a secret token enables runtime control (e.g. starting demo mode) without exposing any UI or storing credentials in files.

## Platform

- **Provider:** Scalingo (Scalingo SAS, Strasbourg, France)
- **Subdomain:** `<appname>.scalingo.io` (TLS included)
- **Container size:** S (256 MB RAM) — sufficient for Flask + SQLite + background thread
- **Cost:** ~€7.20/mo; 30-day free trial available (no credit card)
- **Filesystem:** Ephemeral — acceptable because `valg.db` is fully derived from `valg-data` and can be rebuilt on every start

## Data Flow

```
valg-data (public GitHub repo)
  ↓  cloned on startup, polled every 60s
server.py (background thread)
  ↓  process_directory → valg.db (in-container, ephemeral)
Flask app → /api/* endpoints → browser
```

1. On startup: clone `$VALG_DATA_REPO` (public GitHub URL) into a temp directory
2. Run `process_directory` over the cloned data to build `valg.db`
3. Start serving immediately; background thread polls GitHub API or runs `git fetch` every 60s
4. On new commits detected (HEAD SHA changed): pull + reprocess → replace `valg.db`
5. Rebuild uses a threading lock to prevent concurrent access during swap

## Code Changes

### `pyproject.toml`
Move `flask` from `optional-dependencies.standalone` to `project.dependencies`. Flask is now a required dep for all installs.

### `server.py`
Two existing changes:
- Bind to `0.0.0.0` instead of `127.0.0.1` (Scalingo requires this)
- Respect `PORT` env var injected by Scalingo: `port=int(os.environ.get("PORT", args.port))`

New: startup clone + background polling thread (self-contained, does not touch existing routes or app factory).

### `Procfile` (new file)
```
web: python -m valg.server
```

## Admin API

Two endpoints added to `server.py`, grouped under `/admin/`:

| Method | Path | Body | Effect |
|--------|------|------|--------|
| `POST` | `/admin/demo` | `{"scenario": "kv2025"}` | Start demo mode with named scenario |
| `POST` | `/admin/demo/stop` | — | Stop demo mode |

**Auth:** Every request must include `Authorization: Bearer <token>`. The token is read from `VALG_ADMIN_TOKEN` env var at request time (not cached at startup, so rotation takes effect immediately without restart).

**Error responses:**
- `401 Unauthorized` — token missing or incorrect
- `400 Bad Request` — unknown scenario name
- `200 OK` — action applied

Usage:
```bash
curl -X POST https://valg.scalingo.io/admin/demo \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"scenario": "kv2025"}'
```

## Environment Variables

Set in Scalingo dashboard or via Scalingo CLI. Never stored in any file.

| Variable | Required | Description |
|----------|----------|-------------|
| `VALG_DATA_REPO` | Yes | Public GitHub URL for valg-data repo (e.g. `https://github.com/deterherligt/valg-data.git`) |
| `VALG_ADMIN_TOKEN` | Yes | Secret token for admin API. Generate with `openssl rand -hex 32`. |
| `VALG_AI_API_KEY` | No | Enables AI commentary. Omit to disable. |
| `VALG_AI_MODEL` | No | Defaults to `claude-sonnet-4-6` |

`VALG_SFTP_*` vars are not needed — the server never talks to SFTP directly. GitHub Actions handles that.

## What Does Not Change

- All `/api/*` endpoints
- Flask templates and static assets
- Demo engine (`valg/demo.py`, `valg/scenarios/`)
- CLI (`valg/cli.py`)
- GitHub Actions sync workflow (`sync.yml`)
- SQLite schema and plugins

## Security Notes

- Admin token is never written to any file or committed to any repo
- Token is read from env at request time — rotation requires no restart
- `/admin/*` returns identical `401` for both missing and incorrect tokens (no oracle)
- Dashboard itself remains fully public (read-only, no write surface)
- SFTP credentials are not present on the server

## Out of Scope

- Custom domain (`.dk`) — can be added later via Scalingo's domain settings
- PWA / "Add to Home Screen" — separate task
- Response caching for `/api/parties` D'Hondt calculations — separate task
- Scalingo autoscaling or multi-instance — not needed at current scale
