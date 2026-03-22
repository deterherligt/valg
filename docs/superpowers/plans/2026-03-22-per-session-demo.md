# Per-Session Demo Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give each visitor their own isolated demo — their own SQLite database and their own DemoRunner — identified by a UUID cookie, so one visitor's actions never affect another's view.

**Architecture:** A new `SessionManager` module owns the session lifecycle (create, look up, expire). `create_app` gains a `session_manager` parameter; when present, `_get_conn()` and demo endpoints become session-aware by reading the `valg_session` cookie on each request. Each session gets its own subdirectory under `{APP_DIR}/sessions/{session_id}/` containing `valg.db` and `data/`. `DemoRunner` gains `commit_enabled=False` for per-session runners since session data dirs are not git repos.

**Tech Stack:** Python, Flask, SQLite, threading, pytest.

**Spec:** `docs/superpowers/specs/2026-03-22-per-session-demo-design.md`

---

### Task 1: Add `commit_enabled` flag to `DemoRunner`

**Files:**
- Modify: `valg/demo.py` (`DemoRunner.__init__`, `restart`, `_run`)
- Test: `tests/test_demo.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_demo.py`:

```python
def test_runner_commit_enabled_default_true():
    r = DemoRunner()
    assert r.commit_enabled is True


def test_runner_commit_enabled_false():
    r = DemoRunner(commit_enabled=False)
    assert r.commit_enabled is False
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /Users/madsschmidt/Documents/valg && \
  .venv/bin/pytest tests/test_demo.py::test_runner_commit_enabled_default_true \
                   tests/test_demo.py::test_runner_commit_enabled_false -v
```
Expected: FAIL with `TypeError` (unexpected keyword argument).

- [ ] **Step 3: Implement**

In `valg/demo.py`, update `DemoRunner.__init__`:

```python
def __init__(self, commit_enabled: bool = True) -> None:
    self.state: str = "idle"
    self.speed: float = 1.0
    self.step_index: int = -1
    self.paused: bool = False
    self.scenario_name: str = "Election Night"
    self.commit_enabled: bool = commit_enabled
    self._lock = threading.Lock()
```

In `restart()`, wrap the reset commit:

```python
        if cleaned and self.commit_enabled:
            from valg.fetcher import commit_data_repo
            commit_data_repo(Path(data_repo), message="demo: reset")
```

(Replace the existing `if cleaned:` block — remove the `commit_data_repo` import and call from inside `restart`, add the `commit_enabled` guard.)

In `_run()`, guard the per-step commit:

```python
            if step.commit and self.commit_enabled:
                commit_data_repo(self._data_repo, message=f"demo: {step.name}")
```

(Replace `if step.commit:` with the above.)

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd /Users/madsschmidt/Documents/valg && \
  .venv/bin/pytest tests/test_demo.py -v
```
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add valg/demo.py tests/test_demo.py
git commit -m "feat: add commit_enabled flag to DemoRunner"
```

---

### Task 2: `SessionState` and `SessionManager`

**Files:**
- Create: `valg/sessions.py`
- Create: `tests/test_sessions.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_sessions.py`:

```python
import time
import pytest
from pathlib import Path
from valg.sessions import SessionManager


@pytest.fixture
def mgr(tmp_path):
    return SessionManager(base_dir=tmp_path / "sessions", max_sessions=3)


def test_get_or_create_creates_session(mgr, tmp_path):
    s = mgr.get_or_create("abc")
    assert s is not None
    assert s.session_id == "abc"
    assert s.db_path.exists()
    assert s.data_dir.exists()
    assert s.runner is not None
    assert s.runner.commit_enabled is False


def test_get_or_create_returns_same_session(mgr):
    s1 = mgr.get_or_create("abc")
    s2 = mgr.get_or_create("abc")
    assert s1 is s2


def test_get_or_create_returns_none_at_cap(mgr):
    mgr.get_or_create("s1")
    mgr.get_or_create("s2")
    mgr.get_or_create("s3")
    assert mgr.get_or_create("s4") is None


def test_existing_session_bypasses_cap(mgr):
    mgr.get_or_create("s1")
    mgr.get_or_create("s2")
    mgr.get_or_create("s3")
    # s1 already exists — should return it even though cap is reached
    assert mgr.get_or_create("s1") is not None


def test_get_returns_none_for_unknown(mgr):
    assert mgr.get("unknown") is None


def test_get_returns_existing_session(mgr):
    mgr.get_or_create("abc")
    s = mgr.get("abc")
    assert s is not None
    assert s.session_id == "abc"


def test_cleanup_removes_expired_sessions(mgr, tmp_path):
    s = mgr.get_or_create("old")
    session_dir = s.db_path.parent
    # Force expiry by backdating last_seen
    s.last_seen = time.time() - mgr.TIMEOUT_SECONDS - 1
    mgr._cleanup()
    assert mgr.get("old") is None
    assert not session_dir.exists()


def test_cleanup_keeps_active_sessions(mgr):
    mgr.get_or_create("active")
    mgr._cleanup()
    assert mgr.get("active") is not None
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /Users/madsschmidt/Documents/valg && \
  .venv/bin/pytest tests/test_sessions.py -v
```
Expected: FAIL with `ModuleNotFoundError: No module named 'valg.sessions'`.

- [ ] **Step 3: Implement `valg/sessions.py`**

```python
from __future__ import annotations

import shutil
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class SessionState:
    session_id: str
    db_path: Path
    data_dir: Path
    runner: object  # DemoRunner — avoid circular import
    last_seen: float = field(default_factory=time.time)


class SessionManager:
    TIMEOUT_SECONDS = 1800   # 30 minutes
    CLEANUP_INTERVAL = 300   # 5 minutes

    def __init__(self, base_dir: Path, max_sessions: int = 5) -> None:
        self._base_dir = Path(base_dir)
        self._base_dir.mkdir(parents=True, exist_ok=True)
        self._max_sessions = max_sessions
        self._sessions: dict[str, SessionState] = {}
        self._lock = threading.Lock()
        self._start_cleanup_thread()

    def get_or_create(self, session_id: str) -> Optional[SessionState]:
        with self._lock:
            if session_id in self._sessions:
                self._sessions[session_id].last_seen = time.time()
                return self._sessions[session_id]
            if len(self._sessions) >= self._max_sessions:
                return None
            session = self._create_session(session_id)
            self._sessions[session_id] = session
            return session

    def get(self, session_id: str) -> Optional[SessionState]:
        with self._lock:
            session = self._sessions.get(session_id)
            if session is not None:
                session.last_seen = time.time()
            return session

    def _create_session(self, session_id: str) -> SessionState:
        from valg.demo import DemoRunner
        from valg.models import get_connection, init_db
        session_dir = self._base_dir / session_id
        session_dir.mkdir(parents=True, exist_ok=True)
        db_path = session_dir / "valg.db"
        data_dir = session_dir / "data"
        data_dir.mkdir(exist_ok=True)
        conn = get_connection(db_path)
        init_db(conn)
        conn.close()
        runner = DemoRunner(commit_enabled=False)
        return SessionState(
            session_id=session_id,
            db_path=db_path,
            data_dir=data_dir,
            runner=runner,
        )

    def _cleanup(self) -> None:
        """Remove expired sessions. Call with lock NOT held (stops runners outside lock)."""
        now = time.time()
        with self._lock:
            expired = [
                s for s in self._sessions.values()
                if now - s.last_seen > self.TIMEOUT_SECONDS
            ]
            for s in expired:
                del self._sessions[s.session_id]
        for s in expired:
            self._stop_and_delete(s)

    def _stop_and_delete(self, session: SessionState) -> None:
        try:
            session.runner.pause()
            if hasattr(session.runner, "_thread") and session.runner._thread.is_alive():
                session.runner._thread.join(timeout=5.0)
        except Exception:
            pass
        shutil.rmtree(session.db_path.parent, ignore_errors=True)

    def _start_cleanup_thread(self) -> None:
        def loop() -> None:
            while True:
                time.sleep(self.CLEANUP_INTERVAL)
                self._cleanup()
        t = threading.Thread(target=loop, daemon=True)
        t.start()
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd /Users/madsschmidt/Documents/valg && \
  .venv/bin/pytest tests/test_sessions.py -v
```
Expected: all pass.

- [ ] **Step 5: Run full suite**

```bash
cd /Users/madsschmidt/Documents/valg && .venv/bin/pytest tests/ --ignore=tests/e2e -q
```
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add valg/sessions.py tests/test_sessions.py
git commit -m "feat: add SessionManager for per-session demo isolation"
```

---

### Task 3: Session-aware `create_app`

**Files:**
- Modify: `valg/server.py` (`create_app` signature, `_get_conn`, `GET /`, demo endpoints)
- Test: `tests/test_server.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_server.py`:

```python
import uuid
from valg.sessions import SessionManager


@pytest.fixture
def session_client(tmp_path):
    mgr = SessionManager(base_dir=tmp_path / "sessions", max_sessions=5)
    app = create_app(
        db_path=tmp_path / "valg.db",
        data_dir=tmp_path / "data",
        session_manager=mgr,
    )
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c, mgr


def test_index_sets_session_cookie(session_client):
    c, _ = session_client
    resp = c.get("/")
    assert resp.status_code == 200
    assert "valg_session" in resp.headers.get("Set-Cookie", "")


def test_index_reuses_existing_cookie(session_client):
    c, mgr = session_client
    sid = str(uuid.uuid4())
    mgr.get_or_create(sid)
    c.set_cookie("valg_session", sid)
    resp = c.get("/")
    assert resp.status_code == 200
    # No new session created — still just 1
    assert len(mgr._sessions) == 1


def test_api_parties_uses_session_db(session_client):
    c, mgr = session_client
    sid = str(uuid.uuid4())
    session = mgr.get_or_create(sid)
    # Write data into the session's DB
    from valg.models import get_connection, init_db
    from tests.synthetic.generator import generate_election, load_into_db
    conn = get_connection(session.db_path)
    init_db(conn)
    e = generate_election(seed=42)
    load_into_db(conn, e, phase="preliminary")
    conn.close()
    c.set_cookie("valg_session", sid)
    resp = c.get("/api/parties")
    assert resp.status_code == 200
    parties = resp.get_json()
    assert len(parties) > 0


def test_demo_state_returns_unavailable_without_session(session_client):
    c, _ = session_client
    # No cookie set — no session
    resp = c.get("/demo/state")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["enabled"] is False
    assert data["state"] == "unavailable"


def test_demo_state_returns_runner_state_with_session(session_client):
    c, mgr = session_client
    sid = str(uuid.uuid4())
    mgr.get_or_create(sid)
    c.set_cookie("valg_session", sid)
    resp = c.get("/demo/state")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["enabled"] is True
    assert data["state"] == "idle"


def test_demo_control_dispatches_to_session_runner(session_client):
    c, mgr = session_client
    sid = str(uuid.uuid4())
    mgr.get_or_create(sid)
    c.set_cookie("valg_session", sid)
    resp = c.post("/demo/control", json={"action": "set_speed", "speed": 5.0})
    assert resp.status_code == 200
    assert mgr.get(sid).runner.speed == 5.0


def test_demo_control_returns_404_without_session(session_client):
    c, _ = session_client
    resp = c.post("/demo/control", json={"action": "set_speed", "speed": 2.0})
    assert resp.status_code == 404


def test_two_sessions_see_independent_data(tmp_path):
    """Two sessions with different data in their DBs see only their own data."""
    from valg.sessions import SessionManager
    from valg.server import create_app
    from valg.models import get_connection, init_db
    from tests.synthetic.generator import generate_election, load_into_db

    mgr = SessionManager(base_dir=tmp_path / "sessions", max_sessions=5)
    app = create_app(
        db_path=tmp_path / "valg.db",
        data_dir=tmp_path / "data",
        session_manager=mgr,
    )
    app.config["TESTING"] = True

    sid_a = str(uuid.uuid4())
    sid_b = str(uuid.uuid4())
    session_a = mgr.get_or_create(sid_a)
    session_b = mgr.get_or_create(sid_b)

    # Load data into session A only
    conn_a = get_connection(session_a.db_path)
    init_db(conn_a)
    e = generate_election(seed=1)
    load_into_db(conn_a, e, phase="preliminary")
    conn_a.close()

    # Session B has empty DB (init_db only, no data)
    with app.test_client() as c:
        c.set_cookie("valg_session", sid_a)
        resp_a = c.get("/api/parties")
        parties_a = resp_a.get_json()

    with app.test_client() as c:
        c.set_cookie("valg_session", sid_b)
        resp_b = c.get("/api/parties")
        parties_b = resp_b.get_json()

    assert len(parties_a) > 0, "Session A should see parties"
    assert len(parties_b) == 0, "Session B should see no parties (empty DB)"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /Users/madsschmidt/Documents/valg && \
  .venv/bin/pytest tests/test_server.py::test_index_sets_session_cookie \
                   tests/test_server.py::test_demo_state_returns_unavailable_without_session -v
```
Expected: FAIL (no `session_manager` param on `create_app` yet).

- [ ] **Step 3: Implement session-aware `create_app`**

In `valg/server.py`:

**3a. Add imports at the top of the file:**
```python
import uuid as _uuid
```
(Add alongside existing imports.)

**3b. Update `create_app` signature:**
```python
def create_app(
    db_path: Path = _DEFAULT_DB,
    data_dir: Path = _DEFAULT_DATA,
    demo_runner=None,
    data_repo: Path | None = None,
    session_manager=None,
) -> Flask:
```

**3c. Replace `_get_conn` closure:**
```python
    def _get_conn():
        from valg.models import get_connection, init_db
        if session_manager is not None:
            sid = request.cookies.get("valg_session")
            session = session_manager.get(sid) if sid else None
            conn_path = session.db_path if session is not None else db_path
        else:
            conn_path = db_path
        conn = get_connection(conn_path)
        init_db(conn)
        return conn
```

**3d. Replace the `GET /` route:**
```python
    @app.get("/")
    def index():
        from flask import make_response
        resp = make_response(render_template("index.html"))
        if session_manager is not None:
            sid = request.cookies.get("valg_session") or str(_uuid.uuid4())
            session_manager.get_or_create(sid)
            # Always set the cookie — even if cap exceeded (session is None), so the
            # visitor retains the same ID and won't spam session creation on every reload.
            resp.set_cookie("valg_session", sid, httponly=True, samesite="Lax")
        return resp
```

**3e. Replace the demo endpoint registration block** (the `if demo_runner is not None: ... else: ...` section starting at line 208). Replace the entire block with:

```python
    _demo_repo = data_repo

    if session_manager is not None:
        @app.get("/demo/state")
        def demo_state():
            sid = request.cookies.get("valg_session")
            session = session_manager.get(sid) if sid else None
            if session is None:
                return jsonify({
                    "enabled": False, "state": "unavailable",
                    "scenarios": [], "speed": 1,
                    "step_index": -1, "step_name": "", "steps_total": 0,
                })
            return jsonify(session.runner.get_state_dict())

        @app.post("/demo/control")
        def demo_control():
            sid = request.cookies.get("valg_session")
            session = session_manager.get(sid) if sid else None
            if session is None:
                return "No active session", 404
            data = request.get_json(force=True)
            action = data.get("action", "")
            try:
                if action == "start":
                    session.runner.start(db_path=session.db_path, data_repo=session.data_dir)
                elif action == "pause":
                    session.runner.pause()
                elif action == "resume":
                    session.runner.resume()
                elif action == "restart":
                    session.runner.restart(db_path=session.db_path, data_repo=session.data_dir)
                elif action == "set_speed":
                    session.runner.set_speed(float(data["speed"]))
                elif action == "set_scenario":
                    session.runner.set_scenario(data["scenario"])
                else:
                    return f"Unknown action: {action}", 400
            except (KeyError, ValueError, RuntimeError) as e:
                return str(e), 400
            return "ok", 200

    elif demo_runner is not None:
        @app.get("/demo/state")
        def demo_state():
            return jsonify(demo_runner.get_state_dict())

        @app.post("/demo/control")
        def demo_control():
            data = request.get_json(force=True)
            action = data.get("action", "")
            repo = _demo_repo or Path(os.environ.get("VALG_DATA_REPO", "../valg-data"))
            try:
                if action == "start":
                    demo_runner.start(db_path=db_path, data_repo=repo)
                elif action == "pause":
                    demo_runner.pause()
                elif action == "resume":
                    demo_runner.resume()
                elif action == "restart":
                    demo_runner.restart(db_path=db_path, data_repo=repo)
                elif action == "set_speed":
                    demo_runner.set_speed(float(data["speed"]))
                elif action == "set_scenario":
                    demo_runner.set_scenario(data["scenario"])
                else:
                    return f"Unknown action: {action}", 400
            except (KeyError, ValueError, RuntimeError) as e:
                return str(e), 400
            return "ok", 200

        # ── Admin API ────────────────────────────────────────────────────────────

        def _check_admin_auth():
            token = os.environ.get("VALG_ADMIN_TOKEN")
            if not token:
                return jsonify({"error": "admin not configured"}), 503
            auth = request.headers.get("Authorization", "")
            if not auth.startswith("Bearer ") or auth[len("Bearer "):] != token:
                return jsonify({"error": "unauthorized"}), 401
            return None

        @app.post("/admin/demo")
        def admin_demo_start():
            err = _check_admin_auth()
            if err is not None:
                return err
            body = request.get_json(silent=True) or {}
            scenario = body.get("scenario", "")
            from valg.demo import SCENARIOS
            if scenario not in SCENARIOS:
                return jsonify({"error": f"unknown scenario: {scenario!r}"}), 400
            demo_runner.set_scenario(scenario)
            if "speed" in body:
                demo_runner.set_speed(float(body["speed"]))
            demo_runner.start(db_path=db_path, data_repo=data_repo or Path(os.environ.get("VALG_DATA_REPO", "../valg-data")))
            return jsonify({"status": "started", "scenario": scenario}), 200

        @app.post("/admin/demo/stop")
        def admin_demo_stop():
            err = _check_admin_auth()
            if err is not None:
                return err
            demo_runner.pause()
            return jsonify({"status": "stopped"}), 200

    else:
        @app.get("/demo/state")
        def demo_state_disabled():
            return "Demo mode not enabled", 404

        @app.post("/demo/control")
        def demo_control_disabled():
            return "Demo mode not enabled", 404
```

Note: Flask requires unique function names for routes. The three `demo_state` / `demo_control` functions are inside separate `if/elif/else` branches so only one is ever defined per app instance — this is fine.

- [ ] **Step 4: Run new tests**

```bash
cd /Users/madsschmidt/Documents/valg && \
  .venv/bin/pytest tests/test_server.py::test_index_sets_session_cookie \
                   tests/test_server.py::test_index_reuses_existing_cookie \
                   tests/test_server.py::test_api_parties_uses_session_db \
                   tests/test_server.py::test_demo_state_returns_unavailable_without_session \
                   tests/test_server.py::test_demo_state_returns_runner_state_with_session \
                   tests/test_server.py::test_demo_control_dispatches_to_session_runner \
                   tests/test_server.py::test_demo_control_returns_404_without_session \
                   tests/test_server.py::test_two_sessions_see_independent_data -v
```
Expected: all PASS.

- [ ] **Step 5: Run full suite**

```bash
cd /Users/madsschmidt/Documents/valg && .venv/bin/pytest tests/ --ignore=tests/e2e -q
```
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add valg/server.py tests/test_server.py
git commit -m "feat: session-aware create_app with per-session DB and demo runner"
```

---

### Task 4: Wire `SessionManager` into `main()`

**Files:**
- Modify: `valg/server.py` (`main` function only)

No new tests needed — the integration is covered by Task 3's tests. The existing `main()` tests (if any) continue to pass because `session_manager` defaults to `None`.

- [ ] **Step 1: Update `main()`**

In `valg/server.py`, replace the `main()` function body from the demo runner creation onward:

Find:
```python
    from valg.demo import DemoRunner
    demo_runner = DemoRunner()

    t = threading.Thread(target=_sync_loop, args=(data_dir, db_path), daemon=True)
    t.start()

    app = create_app(
        db_path=db_path,
        data_dir=data_dir,
        demo_runner=demo_runner,
        data_repo=data_repo,
    )
```

Replace with:
```python
    from valg.sessions import SessionManager
    session_manager = SessionManager(base_dir=_APP_DIR / "sessions")

    t = threading.Thread(target=_sync_loop, args=(data_dir, db_path), daemon=True)
    t.start()

    app = create_app(
        db_path=db_path,
        data_dir=data_dir,
        session_manager=session_manager,
        data_repo=data_repo,
    )
```

- [ ] **Step 2: Run full suite**

```bash
cd /Users/madsschmidt/Documents/valg && .venv/bin/pytest tests/ --ignore=tests/e2e -q
```
Expected: all pass.

- [ ] **Step 3: Commit**

```bash
git add valg/server.py
git commit -m "feat: wire SessionManager into server main()"
```

---

### Task 5: Open PR

- [ ] **Step 1: Push and open PR**

```bash
git push -u origin HEAD
gh pr create \
  --title "Per-session demo isolation" \
  --body "$(cat <<'EOF'
## Summary
- Each visitor gets their own isolated demo via `valg_session` UUID cookie
- New `SessionManager` creates per-session SQLite DB + `DemoRunner` under `sessions/{id}/`
- Sessions expire after 30 min inactivity; cleanup thread stops runner and deletes files
- Max 5 concurrent sessions (configurable); visitors above cap see empty dashboard
- `DemoRunner` gains `commit_enabled=False` flag — per-session runners skip git commits
- Shared `demo_runner` path preserved for non-session deployments

## Test plan
- [ ] `pytest tests/test_sessions.py` — SessionManager lifecycle, cap, cleanup
- [ ] `pytest tests/test_server.py` — cookie set on GET /, session DB isolation, demo state
- [ ] Start server with `--demo`, open two browser tabs, verify independent demo control

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```
