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

- `get_or_create(session_id) -> SessionState | None` — returns existing session (updating `last_seen`) or creates a new one. Returns `None` when at cap.
- `get(session_id) -> SessionState | None` — looks up without creating.
- Background cleanup thread runs every 5 minutes, removes sessions where `time.time() - last_seen > TIMEOUT_SECONDS` (default 1800 = 30 min). On removal: stops runner, deletes session directory.
- `MAX_SESSIONS = 5` (configurable via constructor).

Session files live under `{base_dir}/sessions/{session_id}/`:
- `valg.db` — the session's SQLite database
- `data/` — temporary data directory for the runner (no git repo)

### `valg/demo.py`

`DemoRunner.__init__` gains `commit_enabled: bool = True`. When `False`, all `commit_data_repo(...)` calls are skipped. Per-session runners always use `commit_enabled=False` since session data dirs are not git repositories.

### `valg/server.py`

`create_app` gains `session_manager: SessionManager | None = None`. When provided:

- `GET /` reads `valg_session` cookie; if absent or unknown, calls `session_manager.get_or_create()` and sets the cookie on the response.
- `_get_conn()` looks up the session cookie, finds the session's `db_path`, returns a connection to it.
- Demo endpoints (`/demo/state`, `/demo/control`) look up the session's `runner` instead of the shared `demo_runner`.
- When `get_or_create` returns `None` (cap reached): `GET /` still loads the page (visitor sees empty dashboard), `/demo/state` returns `{"enabled": false, "state": "unavailable", "scenarios": [], "speed": 1}`.

`main()` creates a `SessionManager` and passes it to `create_app`. The existing `demo_runner` argument is removed from `create_app` when `session_manager` is provided — each session brings its own runner.

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
