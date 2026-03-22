# Per-Session Demo Design

## Goal

Each visitor controls their own isolated demo — their own data, their own runner state. No visitor can affect another's view.

## Architecture

Three layers of change: a new `SessionManager` module, session-aware wiring in `server.py`, and a `commit_enabled` flag on `DemoRunner`.

### `valg/sessions.py` (new)

`SessionState` holds everything belonging to one visitor:

```python
@dataclass
class SessionState:
    session_id: str
    db_path: Path
    data_dir: Path
    runner: DemoRunner
    last_seen: float  # time.time()
```

`SessionManager` is a thread-safe dict of `session_id → SessionState`:

- `get_or_create(session_id) -> SessionState | None` — if session already exists, updates `last_seen` and returns it (existing sessions always bypass the cap check). If new, creates one unless `len(sessions) >= MAX_SESSIONS`, in which case returns `None`.
- `get(session_id) -> SessionState | None` — looks up without creating, updates `last_seen` if found.
- Background cleanup thread runs every 5 minutes, removes sessions where `time.time() - last_seen > TIMEOUT_SECONDS` (default 1800 = 30 min). On removal: calls `runner.pause()` then joins the thread (synchronous stop), then deletes the session directory, then removes from map.
- `MAX_SESSIONS = 5` (configurable via constructor).

Session files live under `base_dir/{session_id}/` where `base_dir` defaults to `_APP_DIR / "sessions"`:
- `valg.db` — the session's SQLite database
- `data/` — temporary data directory for the runner (no git repo)

### `valg/demo.py`

`DemoRunner.__init__` gains `commit_enabled: bool = True`. When `False`, all `commit_data_repo(...)` calls are skipped. Per-session runners always use `commit_enabled=False` since session data dirs are not git repositories.

### `valg/server.py`

`create_app` signature becomes `create_app(db_path, data_dir, demo_runner=None, data_repo=None, session_manager=None)`. When `session_manager` is provided, `demo_runner` is passed as `None` — the two are mutually exclusive. The existing `if demo_runner is not None` block that registers demo endpoints is replaced by a new block: `if session_manager is not None` registers session-aware demo endpoints, `elif demo_runner is not None` registers the existing shared endpoints. This replaces both existing demo registration blocks.

When `session_manager` is provided:

- `GET /` reads `valg_session` cookie; if absent or unknown, calls `session_manager.get_or_create()` and sets the cookie on the response. If `get_or_create` returns `None` (cap reached), the cookie is still set but no session state exists.
- `_get_conn()` is redefined to call `flask.request.cookies.get('valg_session')` directly, look up the session via `session_manager.get(session_id)`, and return a connection to `session.db_path`. Falls back to the shared `db_path` if no session found.
- `/demo/state` looks up the session's `runner`; if no session exists (cap exceeded), returns `{"enabled": false, "state": "unavailable", "scenarios": [], "speed": 1}`.
- `/demo/control` looks up the session's `runner` and dispatches the action to it.

`main()` creates a `SessionManager(base_dir=_APP_DIR / "sessions")` and passes it to `create_app` with `demo_runner=None`.

Cookie properties: name `valg_session`, `HttpOnly`, `SameSite=Lax`, no explicit expiry (browser session lifetime).

### Frontend

No changes. The cookie is sent automatically with every request. The demo bar is hidden when `demo.enabled` is `False` (existing behaviour), which covers the cap-exceeded case.

## Data Flow

```
Browser (GET /)
  → server sets valg_session cookie if absent
  → SessionManager.get_or_create() → SessionState or None

Browser (GET /api/parties)
  → _get_conn() reads cookie → session db_path → SQLite connection

Browser (POST /demo/control)
  → server reads cookie → session.runner → DemoRunner action
```

## Session Lifecycle

1. First page load → cookie set, `SessionState` created, empty DB initialised.
2. Visitor starts demo → session's `DemoRunner` starts, writes to session's `db_path`.
3. Visitor interacts → all API reads from session's DB.
4. 30 min inactivity → cleanup thread stops runner, deletes `sessions/{id}/`, removes from map.
5. Next page load after expiry → new session created (new cookie if old session is gone, or same cookie triggers a fresh `get_or_create`).

## Capacity Safeguard

`MAX_SESSIONS` (default 5) limits concurrent active sessions. When reached, new visitors get `demo.enabled = false` and see an empty dashboard. No error page required. Active sessions are unaffected.

## Testing

- Unit tests for `SessionManager`: create, get, cap enforcement, cleanup expiry, thread safety.
- Integration test: two sessions in parallel see independent data.
- Existing server/demo tests continue to pass (they use the non-session code path).
