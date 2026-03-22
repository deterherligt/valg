# Demo/Live Header Indicator & Auto-Exit Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Show a persistent DEMO/LIVE badge in the header and automatically switch all demo sessions to live data the moment the first real election-night results arrive.

**Architecture:** `SessionState` gains a `live` flag; `SessionManager.switch_all_to_live()` sets it on all sessions and stops their runners without deleting directories. A module-level `_maybe_switch_to_live()` helper (called from `_sync_loop`) queries the shared db for preliminary results and triggers the switch exactly once. `_get_conn` and `/demo/state` both respect `session.live`. The header `.meta` span is replaced with an Alpine.js conditional showing either an amber DEMO badge or a green pulsing LIVE badge; `_fetchDemoState` triggers a full data refresh when the demo→live transition is detected.

**Tech Stack:** Python, SQLite, Flask, Alpine.js, pytest.

**Spec:** `docs/superpowers/specs/2026-03-22-demo-live-indicator-design.md`

---

## File Map

| File | Change |
|---|---|
| `valg/sessions.py` | Add `live: bool = False` to `SessionState`; add `switch_all_to_live()` to `SessionManager` |
| `valg/server.py` | Add `_live_data_available` global + `_maybe_switch_to_live()`; update `_get_conn`, `/demo/state`, `_sync_loop`, `main()` |
| `valg/static/app.js` | Update `_fetchDemoState` to trigger `_fetchAll()` on demo→live transition |
| `valg/templates/index.html` | Replace `.meta` span with DEMO/LIVE conditional badge |
| `valg/static/app.css` | Add `.badge`, `.badge--demo`, `.badge--live`, `.badge-dot`, `@keyframes badge-pulse` |
| `tests/test_sessions.py` | Four new tests for `switch_all_to_live` |
| `tests/test_server.py` | Four new tests for `_get_conn`, `/demo/state`, `_maybe_switch_to_live` |

---

### Task 1: `sessions.py` — `live` flag and `switch_all_to_live()`

**Files:**
- Modify: `valg/sessions.py`
- Test: `tests/test_sessions.py`

**Background:** `SessionState` is a dataclass at `sessions.py:14`. `SessionManager._stop_and_delete` at `sessions.py:101` shows the runner-stop pattern to reuse (set `_stop_event`, set `_pause_event`, join thread) — `switch_all_to_live` does the same but skips `shutil.rmtree`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_sessions.py` (after the last test):

```python
def test_switch_all_to_live_sets_live_flag(mgr):
    s1 = mgr.get_or_create(SID1)
    s2 = mgr.get_or_create(SID2)
    mgr.switch_all_to_live()
    assert s1.live is True
    assert s2.live is True


def test_switch_all_to_live_signals_stop_event(mgr):
    s1 = mgr.get_or_create(SID1)
    mgr.switch_all_to_live()
    assert s1.runner._stop_event.is_set()


def test_switch_all_to_live_preserves_session_directories(mgr):
    s1 = mgr.get_or_create(SID1)
    session_dir = s1.db_path.parent
    mgr.switch_all_to_live()
    assert session_dir.exists()
    assert s1.db_path.exists()


def test_switch_all_to_live_is_idempotent(mgr):
    s1 = mgr.get_or_create(SID1)
    mgr.switch_all_to_live()
    mgr.switch_all_to_live()  # second call must not raise
    assert s1.live is True
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /Users/madsschmidt/Documents/valg && \
  .venv/bin/pytest tests/test_sessions.py::test_switch_all_to_live_sets_live_flag \
                   tests/test_sessions.py::test_switch_all_to_live_signals_stop_event \
                   tests/test_sessions.py::test_switch_all_to_live_preserves_session_directories \
                   tests/test_sessions.py::test_switch_all_to_live_is_idempotent -v
```
Expected: FAIL with `AttributeError: 'SessionState' object has no attribute 'live'` or similar.

- [ ] **Step 3: Add `live` field to `SessionState`**

In `valg/sessions.py`, find the `SessionState` dataclass (line 14). Add `live` after `last_seen`:

```python
@dataclass
class SessionState:
    session_id: str
    db_path: Path
    data_dir: Path
    runner: object  # DemoRunner — avoid circular import
    last_seen: float = field(default_factory=time.time)
    live: bool = False
```

- [ ] **Step 4: Add `switch_all_to_live()` to `SessionManager`**

In `valg/sessions.py`, add this method to `SessionManager` after `get` (before `_create_session`):

```python
def switch_all_to_live(self) -> None:
    """Mark all active sessions as live and stop their demo runners.

    Sessions are kept alive (directories preserved) so cookies remain valid.
    """
    with self._lock:
        runners = []
        for session in self._sessions.values():
            if not session.live:
                session.live = True
                runners.append(session.runner)
    for runner in runners:
        try:
            if hasattr(runner, "_stop_event"):
                runner._stop_event.set()
            if hasattr(runner, "_pause_event"):
                runner._pause_event.set()
            if hasattr(runner, "_thread") and runner._thread is not None and runner._thread.is_alive():
                runner._thread.join(timeout=5.0)
        except Exception:
            pass
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
cd /Users/madsschmidt/Documents/valg && \
  .venv/bin/pytest tests/test_sessions.py::test_switch_all_to_live_sets_live_flag \
                   tests/test_sessions.py::test_switch_all_to_live_signals_stop_event \
                   tests/test_sessions.py::test_switch_all_to_live_preserves_session_directories \
                   tests/test_sessions.py::test_switch_all_to_live_is_idempotent -v
```
Expected: all PASS.

- [ ] **Step 6: Run full suite**

```bash
cd /Users/madsschmidt/Documents/valg && .venv/bin/pytest tests/ --ignore=tests/e2e -q
```
Expected: all pass.

- [ ] **Step 7: Commit**

```bash
cd /Users/madsschmidt/Documents/valg && \
  git add valg/sessions.py tests/test_sessions.py && \
  git commit -m "feat: add SessionState.live flag and SessionManager.switch_all_to_live()"
```

---

### Task 2: `server.py` — live detection and routing

**Files:**
- Modify: `valg/server.py`
- Test: `tests/test_server.py`

**Background — what to change and where:**
- `server.py:33-35`: module-level sync globals — add `_live_data_available` here
- `server.py:50-60`: `_get_conn` closure inside `create_app` — update the `conn_path` line
- `server.py:228`: `/demo/state` endpoint — extend the `if session is None:` guard
- `server.py:341`: `_sync_loop` function — add `session_manager=None` param and call `_maybe_switch_to_live`
- `server.py:407`: `threading.Thread` call in `main()` — pass `session_manager`
- New module-level function `_maybe_switch_to_live` — add between `_sync_lock` globals and `create_app`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_server.py` (after the last test):

```python
def test_get_conn_uses_shared_db_when_session_live(tmp_path):
    """When session.live=True, _get_conn routes to the shared db, not the session db."""
    from valg.sessions import SessionManager
    from valg.models import get_connection, init_db
    from tests.synthetic.generator import generate_election, load_into_db

    shared_db = tmp_path / "shared.db"
    conn = get_connection(str(shared_db))
    init_db(conn)
    e = generate_election(seed=42)
    load_into_db(conn, e, phase="preliminary")
    conn.close()

    sid = "aa000000-0000-0000-0000-000000000001"
    mgr = SessionManager(base_dir=tmp_path / "sessions", max_sessions=5)
    app = create_app(db_path=shared_db, data_dir=tmp_path / "data", session_manager=mgr)
    app.config["TESTING"] = True
    with app.test_client() as c:
        c.get("/", headers={"Cookie": f"valg_session={sid}"})
        # Session db is empty; shared db has parties
        session = mgr.get(sid)
        assert session is not None
        resp_before = c.get("/api/parties", headers={"Cookie": f"valg_session={sid}"})
        assert resp_before.get_json() == []  # session db is empty

        session.live = True  # switch to live
        resp_after = c.get("/api/parties", headers={"Cookie": f"valg_session={sid}"})
        assert len(resp_after.get_json()) > 0  # now reads from shared db


def test_demo_state_returns_disabled_when_session_live(tmp_path):
    """/demo/state returns enabled=false when session.live=True."""
    from valg.sessions import SessionManager

    sid = "aa000000-0000-0000-0000-000000000002"
    mgr = SessionManager(base_dir=tmp_path / "sessions", max_sessions=5)
    app = create_app(
        db_path=tmp_path / "v.db",
        data_dir=tmp_path / "data",
        session_manager=mgr,
    )
    app.config["TESTING"] = True
    with app.test_client() as c:
        c.get("/", headers={"Cookie": f"valg_session={sid}"})
        session = mgr.get(sid)
        # Before live switch: enabled=True
        resp = c.get("/demo/state", headers={"Cookie": f"valg_session={sid}"})
        assert resp.get_json()["enabled"] is True

        session.live = True
        resp = c.get("/demo/state", headers={"Cookie": f"valg_session={sid}"})
        assert resp.get_json()["enabled"] is False


def test_maybe_switch_to_live_triggers_once_on_real_results(tmp_path, monkeypatch):
    """switch_all_to_live is called exactly once even if _maybe_switch_to_live runs twice."""
    from unittest.mock import MagicMock
    import valg.server as srv
    from valg.server import _maybe_switch_to_live
    from valg.models import get_connection, init_db

    db = tmp_path / "test.db"
    conn = get_connection(str(db))
    init_db(conn)
    conn.execute(
        "INSERT INTO results (party_id, votes, count_type, snapshot_at) "
        "VALUES ('A', 100, 'preliminary', '2024-11-05T21:00:00')"
    )
    conn.commit()
    conn.close()

    monkeypatch.setattr(srv, "_live_data_available", False)
    mock_sm = MagicMock()
    _maybe_switch_to_live(db, mock_sm)
    _maybe_switch_to_live(db, mock_sm)  # second call must be a no-op
    mock_sm.switch_all_to_live.assert_called_once()


def test_maybe_switch_to_live_no_op_without_real_results(tmp_path, monkeypatch):
    """switch_all_to_live is NOT called when the shared db has no preliminary results."""
    from unittest.mock import MagicMock
    import valg.server as srv
    from valg.server import _maybe_switch_to_live
    from valg.models import get_connection, init_db

    db = tmp_path / "test.db"
    conn = get_connection(str(db))
    init_db(conn)
    conn.close()

    monkeypatch.setattr(srv, "_live_data_available", False)
    mock_sm = MagicMock()
    _maybe_switch_to_live(db, mock_sm)
    mock_sm.switch_all_to_live.assert_not_called()
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /Users/madsschmidt/Documents/valg && \
  .venv/bin/pytest tests/test_server.py::test_get_conn_uses_shared_db_when_session_live \
                   tests/test_server.py::test_demo_state_returns_disabled_when_session_live \
                   tests/test_server.py::test_maybe_switch_to_live_triggers_once_on_real_results \
                   tests/test_server.py::test_maybe_switch_to_live_no_op_without_real_results -v
```
Expected: FAIL (functions/behaviour missing).

- [ ] **Step 3: Add `_live_data_available` global**

In `valg/server.py`, find the `# ── Sync state` block (line 31). Add `_live_data_available` after `_sync_lock`:

```python
# ── Sync state ────────────────────────────────────────────────────────────────

_last_sync = "never"
_just_synced = False
_live_data_available = False
_sync_lock = threading.Lock()
```

- [ ] **Step 4: Add `_maybe_switch_to_live()` helper**

In `valg/server.py`, add this function after the `_sync_lock` block and before `# ── App factory`:

```python
def _maybe_switch_to_live(db_path: Path, session_manager) -> None:
    """Switch all demo sessions to live data if preliminary results exist in the shared db.

    Called from _sync_loop on every iteration. No-op once _live_data_available is True.
    """
    global _live_data_available
    if session_manager is None or _live_data_available:
        return
    from valg.models import get_connection
    conn = get_connection(db_path)
    has_real = conn.execute(
        "SELECT 1 FROM results WHERE count_type = 'preliminary' LIMIT 1"
    ).fetchone() is not None
    conn.close()
    if has_real:
        session_manager.switch_all_to_live()
        _live_data_available = True
```

- [ ] **Step 5: Update `_get_conn` inside `create_app`**

In `valg/server.py`, find `_get_conn` inside `create_app` (around line 50). Change:

```python
            conn_path = session.db_path if session is not None else db_path
```

To:

```python
            conn_path = db_path if (session is None or session.live) else session.db_path
```

- [ ] **Step 6: Update `/demo/state` guard**

In `valg/server.py`, find the `/demo/state` endpoint (around line 228). Change:

```python
            if session is None:
```

To:

```python
            if session is None or session.live:
```

No other change to this endpoint.

- [ ] **Step 7: Update `_sync_loop` signature and add live-check call**

In `valg/server.py`, find `_sync_loop` (line 341). Change its signature from:

```python
def _sync_loop(data_dir: Path, db_path: Path, interval: int = 60) -> None:
    global _last_sync, _just_synced
```

To:

```python
def _sync_loop(data_dir: Path, db_path: Path, interval: int = 60, session_manager=None) -> None:
    global _last_sync, _just_synced
```

Then, inside the `try:` block, add one line after the `with _sync_lock:` block closes:

```python
            with _sync_lock:
                _last_sync = datetime.now(timezone.utc).strftime("%H:%M:%S UTC")
                _just_synced = count > 0
            _maybe_switch_to_live(db_path, session_manager)
```

- [ ] **Step 8: Update `threading.Thread` call in `main()`**

In `valg/server.py`, find the Thread creation (line 407). Change:

```python
    t = threading.Thread(target=_sync_loop, args=(data_dir, db_path), daemon=True)
```

To:

```python
    t = threading.Thread(target=_sync_loop, args=(data_dir, db_path), kwargs={"session_manager": session_manager}, daemon=True)
```

- [ ] **Step 9: Run the new tests**

```bash
cd /Users/madsschmidt/Documents/valg && \
  .venv/bin/pytest tests/test_server.py::test_get_conn_uses_shared_db_when_session_live \
                   tests/test_server.py::test_demo_state_returns_disabled_when_session_live \
                   tests/test_server.py::test_maybe_switch_to_live_triggers_once_on_real_results \
                   tests/test_server.py::test_maybe_switch_to_live_no_op_without_real_results -v
```
Expected: all PASS.

- [ ] **Step 10: Run full suite**

```bash
cd /Users/madsschmidt/Documents/valg && .venv/bin/pytest tests/ --ignore=tests/e2e -q
```
Expected: all pass.

- [ ] **Step 11: Commit**

```bash
cd /Users/madsschmidt/Documents/valg && \
  git add valg/server.py tests/test_server.py && \
  git commit -m "feat: auto-exit demo on real results, route live sessions to shared db"
```

---

### Task 3: Frontend — DEMO/LIVE badge, `_fetchDemoState` refresh

**Files:**
- Modify: `valg/static/app.js:240-244`
- Modify: `valg/templates/index.html:16-22`
- Modify: `valg/static/app.css` (after `.demo-badge--idle` rule, around line 62)

No new tests. Visual correctness verified manually.

- [ ] **Step 1: Update `_fetchDemoState` in `app.js`**

In `valg/static/app.js`, find `_fetchDemoState` (lines 240-244). Replace:

```javascript
    async _fetchDemoState() {
      const resp = await fetch('/demo/state').catch(() => null)
      if (!resp || !resp.ok) return
      this.demo = await resp.json()
    },
```

With:

```javascript
    async _fetchDemoState() {
      const resp = await fetch('/demo/state').catch(() => null)
      if (!resp || !resp.ok) return
      const wasDemo = this.demo.enabled
      this.demo = await resp.json()
      if (wasDemo && !this.demo.enabled) await this._fetchAll()
    },
```

- [ ] **Step 2: Replace `.meta` span in `index.html`**

In `valg/templates/index.html`, find the `.meta` span (lines 16-22). Replace:

```html
    <span class="meta" :class="{'pulsing': syncing}">
      <span x-text="lastSynced ? 'Synced ' + lastSynced : 'Waiting for sync…'"></span>
      <span x-show="districtsTotal > 0">
        &bull;
        <span x-text="(districtsReported || 0) + '/' + (districtsTotal || 0) + ' districts'"></span>
      </span>
    </span>
```

With:

```html
    <span class="meta" :class="{'pulsing': syncing}">
      <template x-if="demo.enabled">
        <span style="display:inline-flex;align-items:center;gap:6px">
          <span class="badge badge--demo">DEMO</span>
          <span>Simulerede data · live ikke tilgængeligt endnu</span>
        </span>
      </template>
      <template x-if="!demo.enabled">
        <span style="display:inline-flex;align-items:center;gap:6px">
          <span class="badge badge--live"><span class="badge-dot"></span>LIVE</span>
          <span x-text="lastSynced ? 'Opdateret ' + lastSynced : 'Venter på sync…'"></span>
          <span x-show="districtsTotal > 0">&bull; <span x-text="(districtsReported || 0) + '/' + (districtsTotal || 0) + ' kredse'"></span></span>
        </span>
      </template>
    </span>
```

- [ ] **Step 3: Add badge CSS to `app.css`**

In `valg/static/app.css`, find `.demo-badge--idle` rule (around line 62). After the closing `}`, add:

```css
.badge {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  font-size: 11px;
  font-weight: 600;
  padding: 2px 8px;
  border-radius: 99px;
  letter-spacing: .05em;
}
.badge--demo {
  background: #92400e;
  color: #fcd34d;
}
.badge--live {
  background: #14532d;
  color: #4ade80;
}
.badge-dot {
  width: 6px;
  height: 6px;
  background: #4ade80;
  border-radius: 50%;
  animation: badge-pulse 2s ease-in-out infinite;
}
@keyframes badge-pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.35; }
}
```

- [ ] **Step 4: Run full test suite**

```bash
cd /Users/madsschmidt/Documents/valg && .venv/bin/pytest tests/ --ignore=tests/e2e -q
```
Expected: all pass.

- [ ] **Step 5: Manual smoke test**

```bash
cd /Users/madsschmidt/Documents/valg && .venv/bin/python -m valg.server --demo
```

Open `http://localhost:5000`. Verify:
- Header shows amber **DEMO** badge + "Simulerede data · live ikke tilgængeligt endnu"
- Demo control bar still visible below header
- After demo completes or is stopped (pause), the badge should still show DEMO (session still `live=False`)
- In a fresh browser session where demo is not active (if reachable without session), header shows green pulsing **LIVE** + "Venter på sync…"

- [ ] **Step 6: Commit**

```bash
cd /Users/madsschmidt/Documents/valg && \
  git add valg/static/app.js valg/templates/index.html valg/static/app.css && \
  git commit -m "feat: DEMO/LIVE header badge and instant data refresh on live switch"
```

---

### Task 4: Open PR

- [ ] **Step 1: Push and open PR**

```bash
cd /Users/madsschmidt/Documents/valg && git push -u origin HEAD && \
gh pr create \
  --title "Demo/live header indicator and auto-exit on real results" \
  --body "$(cat <<'EOF'
## Summary
- Header now shows a persistent amber **DEMO** badge (\"Simulerede data · live ikke tilgængeligt endnu\") in demo mode and a pulsing green **LIVE** badge (\"Opdateret HH:MM:SS · N/M kredse\") in live mode
- When the first preliminary results arrive in the shared db, all active demo sessions are automatically switched to live data — no page reload, no notification
- Demo sessions switch seamlessly: `_fetchDemoState` detects the transition and triggers `_fetchAll()` immediately
- Session directories are preserved across the switch so cookies remain valid

## Test plan
- [ ] `pytest tests/test_sessions.py` — four new tests for `switch_all_to_live`
- [ ] `pytest tests/test_server.py` — four new tests for `_get_conn` live routing, `/demo/state` live response, `_maybe_switch_to_live` call-once behaviour
- [ ] Manual: start server with `--demo`, verify amber DEMO badge; stop demo (or let it run), verify header text; confirm live state shows green LIVE badge

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```
