# Scalingo Deployment Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deploy the valg Flask dashboard to Scalingo with a startup sync, background polling, and a token-protected admin API for demo mode control.

**Architecture:** The existing `_sync_loop` / `sync_from_github` mechanism is reused unchanged. `main()` gains a synchronous initial sync before binding, always creates a `DemoRunner`, initialises a local git repo for demo data, removes the webbrowser call, and binds to `0.0.0.0` with `PORT`. Two new admin endpoints live inside `create_app` (already has `demo_runner` in scope) and check `VALG_ADMIN_TOKEN` at request time.

**Tech Stack:** Flask, SQLite, `http_fetcher.sync_from_github` (stdlib urllib), `subprocess` for git init, Scalingo PaaS.

**Spec:** `docs/superpowers/specs/2026-03-21-scalingo-deployment-design.md`

---

## File map

| File | Change |
|------|--------|
| `pyproject.toml` | Move `flask` to main deps |
| `Procfile` | New — `web: python -m valg.server` |
| `valg/server.py` | Fix `main()` (6 changes) + add admin endpoints in `create_app` |
| `.env.example` | Add Scalingo form comment for `VALG_DATA_REPO` |
| `tests/test_server.py` | Add tests for DemoRunner-always-on and admin endpoints |

---

## Chunk 1: Procfile + Flask dependency

### Task 1: Move Flask to main deps and add Procfile

**Files:**
- Modify: `pyproject.toml`
- Create: `Procfile`

- [ ] **Step 1: Move `flask` from optional to main dependencies**

In `pyproject.toml`, the current state:
```toml
[project]
dependencies = [
    "paramiko>=3.4",
    "gitpython>=3.1",
    "python-dotenv>=1.0",
    "rich>=13.0",
]

[project.optional-dependencies]
dev        = ["pytest>=8.0", "pytest-cov"]
ai         = ["openai>=1.0"]
standalone = ["flask>=3.0"]
```

Change to:
```toml
[project]
dependencies = [
    "paramiko>=3.4",
    "gitpython>=3.1",
    "python-dotenv>=1.0",
    "rich>=13.0",
    "flask>=3.0",
]

[project.optional-dependencies]
dev        = ["pytest>=8.0", "pytest-cov"]
ai         = ["openai>=1.0"]
```

Remove the `standalone` optional group entirely.

- [ ] **Step 2: Create `Procfile`**

```
web: python -m valg.server
```

- [ ] **Step 3: Verify install still works**

```bash
pip install -e ".[dev]"
```
Expected: no errors, flask installed.

- [ ] **Step 4: Run full test suite**

```bash
pytest tests/ -q --tb=short
```
Expected: all tests pass (same count as before).

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml Procfile
git commit -m "feat(deploy): add Procfile and move flask to main dependencies"
```

---

## Chunk 2: server.py startup fixes

### Task 2: Fix `main()` — webbrowser, bind address, PORT, DemoRunner always-on

**Files:**
- Modify: `valg/server.py`
- Modify: `tests/test_server.py`

- [ ] **Step 1: Write a failing test — DemoRunner always instantiated**

The existing `test_demo_state_not_enabled` checks that `/demo/state` returns 404 when no DemoRunner is passed. After this task, DemoRunner is always created, so `/demo/state` should return 200. Add to `tests/test_server.py`:

```python
def test_demo_state_accessible_without_demo_flag(tmp_path):
    """DemoRunner is always created; /demo/state must be reachable."""
    from valg.demo import DemoRunner
    app = create_app(
        db_path=tmp_path / "test.db",
        data_dir=tmp_path / "data",
        demo_runner=DemoRunner(),
    )
    app.config["TESTING"] = True
    with app.test_client() as c:
        resp = c.get("/demo/state")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["state"] == "idle"
```

- [ ] **Step 2: Run test — expect it to pass already (DemoRunner passed in)**

```bash
pytest tests/test_server.py::test_demo_state_accessible_without_demo_flag -v
```
Expected: PASS — `create_app` already handles this; the test documents the contract.

- [ ] **Step 3: Remove `webbrowser.open` call from `main()`**

In `valg/server.py`, remove this line (currently line 296):
```python
threading.Timer(1.0, lambda: webbrowser.open(f"http://localhost:{args.port}")).start()
```
Also remove the `import webbrowser` at the top of the file if it is only used there.

- [ ] **Step 4: Change bind address and respect PORT env var**

In `valg/server.py`, change the `app.run(...)` call (currently line 303):
```python
# Before:
app.run(host="127.0.0.1", port=args.port)
# After:
app.run(host="0.0.0.0", port=int(os.environ.get("PORT", args.port)))
```

- [ ] **Step 5: Always instantiate DemoRunner — remove `--demo` guard**

In `valg/server.py` `main()`, replace:
```python
demo_runner = None
if args.demo:
    from valg.demo import DemoRunner
    demo_runner = DemoRunner()
```
With:
```python
from valg.demo import DemoRunner
demo_runner = DemoRunner()
```
The `--demo` argparse argument can remain (it does nothing now but removing it is a breaking CLI change).

- [ ] **Step 6: Run full test suite**

```bash
pytest tests/ -q --tb=short
```
Expected: all pass. The old `test_demo_state_not_enabled` and `test_demo_control_not_enabled` tests (which expected 404) will now fail — delete or update them.

If those tests exist, update them:
```python
# Delete test_demo_state_not_enabled and test_demo_control_not_enabled
# (DemoRunner is always active; these 404 paths no longer exist)
```

- [ ] **Step 7: Commit**

```bash
git add valg/server.py tests/test_server.py
git commit -m "feat(deploy): fix server.py for Scalingo — bind 0.0.0.0, PORT env var, always-on DemoRunner"
```

### Task 3: git init for demo data_repo + initial sync on startup

**Files:**
- Modify: `valg/server.py`
- Modify: `.env.example`

- [ ] **Step 1: Add git init logic for data_repo in `main()`**

After `data_repo` is resolved in `main()`, add:
```python
import subprocess as _sp
data_repo.mkdir(parents=True, exist_ok=True)
if not (data_repo / ".git").exists():
    _sp.run(["git", "init"], cwd=str(data_repo), check=True)
    _sp.run(["git", "config", "user.email", "valg@localhost"], cwd=str(data_repo), check=True)
    _sp.run(["git", "config", "user.name", "valg"], cwd=str(data_repo), check=True)
```
This is a no-op when `../valg-data` already exists as a git repo (local dev). On Scalingo with `/tmp/valg-demo-data`, it creates a fresh repo.

- [ ] **Step 2: Add initial synchronous sync before binding**

After `load_plugins()` and after the git init block, add:
```python
from valg.http_fetcher import sync_from_github
from valg.models import get_connection, init_db
from valg.processor import process_directory

log.info("Running initial sync from GitHub...")
sync_from_github(data_dir)
_init_conn = get_connection(db_path)
init_db(_init_conn)
process_directory(_init_conn, data_dir)
_init_conn.close()
log.info("Initial sync complete.")
```
This must appear before `app = create_app(...)` and before `app.run(...)`.

- [ ] **Step 3: Update `.env.example`**

Add below the `VALG_DATA_REPO` line:
```
# On Scalingo, use a writable local path (git initialised automatically):
# VALG_DATA_REPO=/tmp/valg-demo-data
```

- [ ] **Step 4: Run full test suite**

```bash
pytest tests/ -q --tb=short
```
Expected: all pass. The initial sync runs in `main()` which tests don't call directly — no test impact.

- [ ] **Step 5: Commit**

```bash
git add valg/server.py .env.example
git commit -m "feat(deploy): add startup sync and git-init for demo data_repo"
```

---

## Chunk 3: Admin API

### Task 4: Token-protected admin endpoints in `create_app`

**Files:**
- Modify: `valg/server.py`
- Modify: `tests/test_server.py`

The admin endpoints live inside `create_app` (where `demo_runner`, `db_path`, and `data_repo` are already in scope). The token is read from `os.environ.get("VALG_ADMIN_TOKEN")` at request time.

- [ ] **Step 1: Write failing tests for `/admin/demo`**

Add to `tests/test_server.py`:

```python
import os
from unittest.mock import patch, MagicMock
from valg.demo import DemoRunner


@pytest.fixture
def admin_client(tmp_path, monkeypatch):
    monkeypatch.setenv("VALG_ADMIN_TOKEN", "test-secret")
    from valg.demo import DemoRunner
    runner = DemoRunner()
    app = create_app(
        db_path=tmp_path / "test.db",
        data_dir=tmp_path / "data",
        demo_runner=runner,
        data_repo=tmp_path / "data-repo",
    )
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c, runner


def test_admin_demo_no_token_configured_returns_503(tmp_path, monkeypatch):
    monkeypatch.delenv("VALG_ADMIN_TOKEN", raising=False)
    from valg.demo import DemoRunner
    app = create_app(
        db_path=tmp_path / "test.db",
        data_dir=tmp_path / "data",
        demo_runner=DemoRunner(),
    )
    app.config["TESTING"] = True
    with app.test_client() as c:
        resp = c.post("/admin/demo", json={"scenario": "kv2025"})
    assert resp.status_code == 503


def test_admin_demo_wrong_token_returns_401(admin_client):
    c, _ = admin_client
    resp = c.post(
        "/admin/demo",
        json={"scenario": "kv2025"},
        headers={"Authorization": "Bearer wrong-token"},
    )
    assert resp.status_code == 401


def test_admin_demo_missing_token_returns_401(admin_client):
    c, _ = admin_client
    resp = c.post("/admin/demo", json={"scenario": "kv2025"})
    assert resp.status_code == 401


def test_admin_demo_unknown_scenario_returns_400(admin_client):
    c, _ = admin_client
    resp = c.post(
        "/admin/demo",
        json={"scenario": "nonexistent"},
        headers={"Authorization": "Bearer test-secret"},
    )
    assert resp.status_code == 400


def test_admin_demo_valid_starts_demo(tmp_path, monkeypatch):
    monkeypatch.setenv("VALG_ADMIN_TOKEN", "test-secret")
    from valg.demo import DemoRunner, SCENARIOS
    runner = DemoRunner()
    scenario_name = next(iter(SCENARIOS))  # first registered scenario
    db = tmp_path / "test.db"
    data_repo = tmp_path / "data-repo"
    app = create_app(
        db_path=db,
        data_dir=tmp_path / "data",
        demo_runner=runner,
        data_repo=data_repo,
    )
    app.config["TESTING"] = True
    with patch.object(runner, "set_scenario") as mock_set, \
         patch.object(runner, "start") as mock_start:
        with app.test_client() as c:
            resp = c.post(
                "/admin/demo",
                json={"scenario": scenario_name},
                headers={"Authorization": "Bearer test-secret"},
            )
        assert resp.status_code == 200
        mock_set.assert_called_once_with(scenario_name)
        mock_start.assert_called_once_with(db_path=db, data_repo=data_repo)


def test_admin_demo_stop_valid_pauses_demo(tmp_path, monkeypatch):
    monkeypatch.setenv("VALG_ADMIN_TOKEN", "test-secret")
    from valg.demo import DemoRunner
    runner = DemoRunner()
    app = create_app(
        db_path=tmp_path / "test.db",
        data_dir=tmp_path / "data",
        demo_runner=runner,
    )
    app.config["TESTING"] = True
    with patch.object(runner, "pause") as mock_pause:
        with app.test_client() as c:
            resp = c.post(
                "/admin/demo/stop",
                headers={"Authorization": "Bearer test-secret"},
            )
        assert resp.status_code == 200
        mock_pause.assert_called_once()


def test_admin_demo_stop_wrong_token_returns_401(admin_client):
    c, _ = admin_client
    resp = c.post(
        "/admin/demo/stop",
        headers={"Authorization": "Bearer wrong-token"},
    )
    assert resp.status_code == 401
```

- [ ] **Step 2: Run tests — expect FAIL**

```bash
pytest tests/test_server.py -k "admin" -v
```
Expected: all FAIL with 404 (routes not yet defined).

- [ ] **Step 3: Add admin endpoints inside `create_app`**

In `valg/server.py`, inside `create_app`, after the existing demo routes block (around line 240), add:

```python
# ── Admin API ─────────────────────────────────────────────────────────────────

def _check_admin_auth():
    """Returns None if authorised, or a Response if not."""
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
    demo_runner.start(db_path=db_path, data_repo=data_repo or Path(os.environ.get("VALG_DATA_REPO", "../valg-data")))
    return jsonify({"status": "started", "scenario": scenario}), 200

@app.post("/admin/demo/stop")
def admin_demo_stop():
    err = _check_admin_auth()
    if err is not None:
        return err
    demo_runner.pause()
    return jsonify({"status": "stopped"}), 200
```

Note: `_check_admin_auth` is a nested function inside `create_app`, so it has access to `request` (imported at top of file) and `os` (stdlib). `db_path` and `data_repo` are already in scope from `create_app`'s parameters.

The admin routes are only registered when `demo_runner is not None`. Add the block inside the `if demo_runner is not None:` block (alongside the existing `/demo/state` and `/demo/control` routes).

- [ ] **Step 4: Run tests — expect PASS**

```bash
pytest tests/test_server.py -k "admin" -v
```
Expected: all PASS.

- [ ] **Step 5: Run full test suite**

```bash
pytest tests/ -q --tb=short
```
Expected: all 250+ tests pass.

- [ ] **Step 6: Commit**

```bash
git add valg/server.py tests/test_server.py
git commit -m "feat(deploy): add token-protected admin API for demo mode control"
```

---

## Chunk 4: Final verification

### Task 5: End-to-end check and push

**Files:** none

- [ ] **Step 1: Run full test suite one final time**

```bash
pytest tests/ -v --tb=short
```
Expected: all pass, no warnings about missing imports.

- [ ] **Step 2: Verify Procfile and pyproject.toml look correct**

```bash
cat Procfile
# Expected: web: python -m valg.server

grep "flask" pyproject.toml
# Expected: flask appears under [project] dependencies, NOT under [project.optional-dependencies]
```

- [ ] **Step 3: Verify server starts cleanly (skip actual sync)**

```bash
VALG_DATA_REPO=/tmp/test-valg-repo \
  python -c "
from valg.server import create_app
from valg.demo import DemoRunner
import tempfile, pathlib
tmp = pathlib.Path(tempfile.mkdtemp())
app = create_app(db_path=tmp/'test.db', data_dir=tmp/'data', demo_runner=DemoRunner())
print('create_app OK')
"
```
Expected: prints `create_app OK` with no import errors.

- [ ] **Step 4: Push to remote**

```bash
git push origin master
```

---

## Scalingo setup checklist (manual, post-deploy)

After pushing, do these steps in the Scalingo dashboard / CLI:

1. Create a new Scalingo app
2. Connect the GitHub repo and enable auto-deploy from `master`
3. Set environment variables (never in files):
   - `VALG_ADMIN_TOKEN` = output of `openssl rand -hex 32`
   - `VALG_DATA_REPO` = `/tmp/valg-demo-data`
4. Trigger first deploy
5. Verify `https://<appname>.scalingo.io/api/status` returns JSON
6. Test admin endpoint:
   ```bash
   curl -X POST https://<appname>.scalingo.io/admin/demo/stop \
     -H "Authorization: Bearer <your-token>"
   # Expected: {"status": "stopped"}
   ```
