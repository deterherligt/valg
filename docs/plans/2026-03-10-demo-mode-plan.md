# Demo Mode Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add an interactive demo mode that streams synthetic election data through the full pipeline (fake files → git commit in `valg-data/` → process into SQLite) with browser-based controls (start, pause, restart, speed).

**Architecture:** `DemoRunner` in `valg/demo.py` runs a background thread stepping through a `Scenario`'s `Step` list, writing fake data to `valg-data/FV2024-demo/`, git-committing after each step, and processing into SQLite. `server.py` gets `/demo/state` and `/demo/control` endpoints and a `--demo` CLI flag. The existing embedded HTML gains a demo control strip that polls state and drives controls.

**Tech Stack:** Python `threading`, `fake_fetcher`, `processor`, `fetcher.commit_data_repo`, Flask (existing), embedded HTML/JS in `server.py`

---

### Task 1: `Step` and `Scenario` dataclasses + `SCENARIOS` registry

**Files:**
- Create: `valg/demo.py`
- Create: `tests/test_demo.py`

**Step 1: Write the failing tests**

```python
# tests/test_demo.py
from valg.demo import Step, Scenario, SCENARIOS, get_scenario


def test_step_defaults():
    s = Step(name="test", wave=1)
    assert s.process is True
    assert s.commit is True
    assert s.setup is False
    assert s.base_interval_s == 60.0


def test_election_night_scenario():
    s = get_scenario("Election Night")
    assert s.name == "Election Night"
    assert len(s.steps) == 6
    assert s.steps[0].setup is True
    assert s.steps[0].wave == 0
    assert s.steps[0].process is False
    assert s.steps[3].wave == 3


def test_get_scenario_unknown():
    import pytest
    with pytest.raises(KeyError):
        get_scenario("Does Not Exist")


def test_scenarios_dict_keys():
    assert "Election Night" in SCENARIOS
```

**Step 2: Run to verify failure**

```bash
pytest tests/test_demo.py -v
```
Expected: `ModuleNotFoundError` — `valg/demo.py` doesn't exist yet.

**Step 3: Implement `valg/demo.py`**

```python
# valg/demo.py
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Step:
    name: str
    wave: int | None
    setup: bool = False
    process: bool = True
    commit: bool = True
    base_interval_s: float = 60.0


@dataclass
class Scenario:
    name: str
    description: str
    steps: list[Step]


SCENARIOS: dict[str, Scenario] = {
    "Election Night": Scenario(
        name="Election Night",
        description=(
            "Simulates a full Folketing election night: "
            "setup → 25/50/100% foreløbig → 50/100% fintælling."
        ),
        steps=[
            Step(name="Setup — geography & candidates", wave=0, setup=True, process=False, commit=True, base_interval_s=0),
            Step(name="25% foreløbig",   wave=1, base_interval_s=60.0),
            Step(name="50% foreløbig",   wave=2, base_interval_s=60.0),
            Step(name="100% foreløbig",  wave=3, base_interval_s=60.0),
            Step(name="50% fintælling",  wave=4, base_interval_s=60.0),
            Step(name="100% fintælling", wave=5, base_interval_s=60.0),
        ],
    ),
}


def get_scenario(name: str) -> Scenario:
    return SCENARIOS[name]
```

**Step 4: Run tests**

```bash
pytest tests/test_demo.py -v
```
Expected: 4 passing.

**Step 5: Commit**

```bash
git add valg/demo.py tests/test_demo.py
git commit -m "feat(demo): Step/Scenario dataclasses and Election Night scenario"
```

---

### Task 2: `DemoRunner` state machine (no loop yet)

**Files:**
- Modify: `valg/demo.py`
- Modify: `tests/test_demo.py`

**Step 1: Write failing tests**

```python
# append to tests/test_demo.py
from valg.demo import DemoRunner


def test_runner_initial_state():
    r = DemoRunner()
    assert r.state == "idle"
    assert r.speed == 1.0
    assert r.step_index == -1
    assert r.paused is False
    assert r.scenario_name == "Election Night"


def test_runner_set_speed():
    r = DemoRunner()
    r.set_speed(5.0)
    assert r.speed == 5.0


def test_runner_set_scenario():
    r = DemoRunner()
    r.set_scenario("Election Night")
    assert r.scenario_name == "Election Night"


def test_runner_set_scenario_unknown():
    import pytest
    r = DemoRunner()
    with pytest.raises(KeyError):
        r.set_scenario("Nope")


def test_runner_set_scenario_rejects_when_running():
    r = DemoRunner()
    r.state = "running"
    import pytest
    with pytest.raises(RuntimeError):
        r.set_scenario("Election Night")


def test_runner_get_state_dict():
    r = DemoRunner()
    d = r.get_state_dict()
    assert d["enabled"] is True
    assert d["state"] == "idle"
    assert d["step_index"] == -1
    assert d["speed"] == 1.0
    assert "Election Night" in d["scenarios"]
```

**Step 2: Run to verify failure**

```bash
pytest tests/test_demo.py::test_runner_initial_state -v
```
Expected: `ImportError` — `DemoRunner` not defined yet.

**Step 3: Implement**

Add to `valg/demo.py` (after existing code):

```python
import logging
import threading

log = logging.getLogger(__name__)


class DemoRunner:
    def __init__(self) -> None:
        self.state: str = "idle"   # idle | running | paused | done
        self.speed: float = 1.0
        self.step_index: int = -1  # -1 = not started
        self.paused: bool = False
        self.scenario_name: str = "Election Night"
        self._lock = threading.Lock()

    def set_speed(self, multiplier: float) -> None:
        with self._lock:
            self.speed = multiplier

    def set_scenario(self, name: str) -> None:
        with self._lock:
            if self.state == "running":
                raise RuntimeError("Cannot change scenario while running")
            get_scenario(name)  # raises KeyError if unknown
            self.scenario_name = name

    def get_state_dict(self) -> dict:
        with self._lock:
            scenario = get_scenario(self.scenario_name)
            step_name = ""
            if 0 <= self.step_index < len(scenario.steps):
                step_name = scenario.steps[self.step_index].name
            return {
                "enabled": True,
                "state": self.state,
                "scenario": self.scenario_name,
                "step_index": self.step_index,
                "step_name": step_name,
                "steps_total": len(scenario.steps),
                "speed": self.speed,
                "scenarios": list(SCENARIOS.keys()),
            }
```

**Step 4: Run tests**

```bash
pytest tests/test_demo.py -v
```
Expected: all passing.

**Step 5: Commit**

```bash
git add valg/demo.py tests/test_demo.py
git commit -m "feat(demo): DemoRunner state machine"
```

---

### Task 3: `reset_db` — clear all rows for restart

**Files:**
- Modify: `valg/models.py`
- Modify: `tests/test_models.py`

**Step 1: Write failing test**

```python
# append to tests/test_models.py
from valg.models import reset_db


def test_reset_db_clears_all_rows():
    conn = get_connection(":memory:")
    init_db(conn)
    conn.execute("INSERT INTO elections (id, name) VALUES ('X', 'Test')")
    conn.commit()
    assert conn.execute("SELECT COUNT(*) FROM elections").fetchone()[0] == 1

    reset_db(conn)

    assert conn.execute("SELECT COUNT(*) FROM elections").fetchone()[0] == 0
    # Schema must still exist
    tables = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()}
    assert "elections" in tables
```

**Step 2: Run to verify failure**

```bash
pytest tests/test_models.py::test_reset_db_clears_all_rows -v
```
Expected: `ImportError` — `reset_db` not defined.

**Step 3: Implement**

Add to `valg/models.py` (after `init_db`):

```python
_TRUNCATE_ORDER = [
    "anomalies", "events", "turnout", "results", "party_votes",
    "candidates", "parties", "afstemningsomraader", "opstillingskredse",
    "storkredse", "elections",
]


def reset_db(conn: sqlite3.Connection) -> None:
    """Delete all rows from all tables. Schema and indexes are preserved."""
    conn.execute("PRAGMA foreign_keys=OFF")
    for table in _TRUNCATE_ORDER:
        conn.execute(f"DELETE FROM {table}")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.commit()
```

**Step 4: Run test**

```bash
pytest tests/test_models.py -v
```
Expected: all passing.

**Step 5: Commit**

```bash
git add valg/models.py tests/test_models.py
git commit -m "feat(demo): add reset_db to models"
```

---

### Task 4: `DemoRunner` wave loop

**Files:**
- Modify: `valg/demo.py`
- Modify: `tests/test_demo.py`

The loop: for each step, write wave files to `data_repo/FV2024-demo/`, optionally commit, optionally process into DB, then sleep `step.base_interval_s / speed` seconds (checking pause and stop every 0.1s).

**Step 1: Write failing test**

```python
# append to tests/test_demo.py
import subprocess
import time
from pathlib import Path


def _init_git_repo(path: Path) -> None:
    subprocess.run(["git", "init"], cwd=path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=path, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=path, capture_output=True)
    (path / "README.md").write_text("demo")
    subprocess.run(["git", "add", "-A"], cwd=path, capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=path, capture_output=True)


def test_runner_runs_election_night(tmp_path):
    """Full Election Night scenario at 100× speed (~0.6s per wave)."""
    from valg.models import get_connection, init_db

    data_repo = tmp_path / "valg-data"
    data_repo.mkdir()
    _init_git_repo(data_repo)

    db_path = tmp_path / "valg.db"
    conn = get_connection(db_path)
    init_db(conn)

    runner = DemoRunner()
    runner.set_speed(100.0)  # 60s / 100 = 0.6s per wave
    runner.start(db_path=db_path, data_repo=data_repo)

    deadline = time.time() + 20
    while runner.state != "done" and time.time() < deadline:
        time.sleep(0.2)

    assert runner.state == "done", f"Runner timed out in state: {runner.state}"
    assert runner.step_index == 5

    conn2 = get_connection(db_path)
    party_votes = conn2.execute("SELECT COUNT(*) FROM party_votes").fetchone()[0]
    assert party_votes > 0, "No party_votes — preliminary phase didn't process"

    final_results = conn2.execute(
        "SELECT COUNT(*) FROM results WHERE count_type='final'"
    ).fetchone()[0]
    assert final_results > 0, "No final results — fintælling phase didn't process"
```

**Step 2: Run to verify failure**

```bash
pytest tests/test_demo.py::test_runner_runs_election_night -v
```
Expected: `AttributeError` — `DemoRunner` has no `start` method.

**Step 3: Implement the loop**

Add the following methods to `DemoRunner` in `valg/demo.py`:

```python
import time
from pathlib import Path


# (inside class DemoRunner)

    def start(self, db_path: Path, data_repo: Path) -> None:
        with self._lock:
            if self.state == "running":
                return
            self.state = "running"
            self.step_index = -1
            self._db_path = Path(db_path)
            self._data_repo = Path(data_repo)
            self._stop_event = threading.Event()
            self._pause_event = threading.Event()
            self._pause_event.set()  # not paused initially
        t = threading.Thread(target=self._run, daemon=True)
        t.start()
        self._thread = t

    def pause(self) -> None:
        with self._lock:
            if self.state != "running":
                return
            self.state = "paused"
            self.paused = True
            self._pause_event.clear()

    def resume(self) -> None:
        with self._lock:
            if self.state != "paused":
                return
            self.state = "running"
            self.paused = False
            self._pause_event.set()

    def _run(self) -> None:
        from valg.fake_fetcher import make_election, setup_db, write_wave
        from valg.processor import process_raw_file
        from valg.plugins import load_plugins
        from valg.fetcher import commit_data_repo
        from valg.models import get_connection, init_db
        from datetime import datetime, timezone

        load_plugins()
        scenario = get_scenario(self.scenario_name)
        election = make_election()
        demo_dir = self._data_repo / "FV2024-demo"
        demo_dir.mkdir(parents=True, exist_ok=True)

        for i, step in enumerate(scenario.steps):
            if self._stop_event.is_set():
                break
            with self._lock:
                self.step_index = i
            log.info("Demo step %d: %s", i, step.name)

            written = []
            if step.wave is not None:
                written = write_wave(demo_dir, election, step.wave)

            if step.setup:
                conn = get_connection(self._db_path)
                init_db(conn)
                setup_db(conn, election)

            if step.process and written:
                conn = get_connection(self._db_path)
                snapshot_at = datetime.now(timezone.utc).isoformat()
                to_process = [p for p in written if not p.name.startswith("kandidat-data")]
                for p in to_process:
                    process_raw_file(conn, p, snapshot_at=snapshot_at)

            if step.commit:
                commit_data_repo(self._data_repo, message=f"demo: {step.name}")

            with self._lock:
                interval = step.base_interval_s / self.speed
            elapsed = 0.0
            tick = 0.1
            while elapsed < interval:
                if self._stop_event.is_set():
                    break
                self._pause_event.wait()  # blocks when paused
                time.sleep(tick)
                elapsed += tick

        with self._lock:
            if not self._stop_event.is_set():
                self.state = "done"
                self.step_index = len(scenario.steps) - 1
```

**Step 4: Run test**

```bash
pytest tests/test_demo.py::test_runner_runs_election_night -v
```
Expected: PASS (takes ~5–10 seconds).

**Step 5: Run full test file**

```bash
pytest tests/test_demo.py -v
```
Expected: all passing.

**Step 6: Commit**

```bash
git add valg/demo.py tests/test_demo.py
git commit -m "feat(demo): DemoRunner wave loop with pause support"
```

---

### Task 5: `DemoRunner.restart`

**Files:**
- Modify: `valg/demo.py`
- Modify: `tests/test_demo.py`

Restart stops the current loop, resets the DB, deletes the demo folder from `valg-data/`, commits the deletion, then calls `start()` again from step 0.

**Step 1: Write failing test**

```python
# append to tests/test_demo.py

def test_runner_restart_clears_data(tmp_path):
    """Restart resets DB and demo folder, then re-runs from step 0."""
    from valg.models import get_connection, init_db

    data_repo = tmp_path / "valg-data"
    data_repo.mkdir()
    _init_git_repo(data_repo)

    db_path = tmp_path / "valg.db"
    conn = get_connection(db_path)
    init_db(conn)

    runner = DemoRunner()
    runner.set_speed(100.0)
    runner.start(db_path=db_path, data_repo=data_repo)

    # Let it process at least one data wave
    deadline = time.time() + 8
    while runner.step_index < 2 and time.time() < deadline:
        time.sleep(0.2)

    runner.restart(db_path=db_path, data_repo=data_repo)

    # After restart the runner should be running again from near step 0
    deadline2 = time.time() + 5
    while runner.step_index < 0 and time.time() < deadline2:
        time.sleep(0.1)

    assert runner.state in ("running", "done")

    # DB party_votes should be empty — wave 0 is setup-only (no results)
    conn2 = get_connection(db_path)
    count = conn2.execute("SELECT COUNT(*) FROM party_votes").fetchone()[0]
    assert count == 0, f"Expected empty party_votes after restart, got {count}"
```

**Step 2: Run to verify failure**

```bash
pytest tests/test_demo.py::test_runner_restart_clears_data -v
```
Expected: `AttributeError` — no `restart` method.

**Step 3: Implement**

Add to `DemoRunner` in `valg/demo.py`:

```python
    def restart(self, db_path: Path, data_repo: Path) -> None:
        # Stop the running loop
        if hasattr(self, "_stop_event"):
            self._stop_event.set()
        if hasattr(self, "_pause_event"):
            self._pause_event.set()  # unblock if paused
        if hasattr(self, "_thread") and self._thread.is_alive():
            self._thread.join(timeout=5.0)

        # Reset DB
        from valg.models import get_connection, reset_db
        reset_db(get_connection(Path(db_path)))

        # Delete demo folder and commit the deletion
        import shutil
        demo_dir = Path(data_repo) / "FV2024-demo"
        if demo_dir.exists():
            shutil.rmtree(demo_dir)
            from valg.fetcher import commit_data_repo
            commit_data_repo(Path(data_repo), message="demo: reset")

        with self._lock:
            self.state = "idle"
            self.step_index = -1
            self.paused = False

        self.start(db_path=db_path, data_repo=data_repo)
```

**Step 4: Run test**

```bash
pytest tests/test_demo.py::test_runner_restart_clears_data -v
```
Expected: PASS.

**Step 5: Run full test file**

```bash
pytest tests/test_demo.py -v
```
Expected: all passing.

**Step 6: Commit**

```bash
git add valg/demo.py tests/test_demo.py
git commit -m "feat(demo): DemoRunner.restart"
```

---

### Task 6: Server demo endpoints

**Files:**
- Modify: `valg/server.py`
- Modify: `tests/test_server.py`

Add `GET /demo/state` and `POST /demo/control`. Without `--demo`, both return 404. Add `--demo` and `--port` flags to `main()`. Pass `data_repo` to `create_app` so the endpoints know where to write.

**Step 1: Write failing tests**

```python
# append to tests/test_server.py


def test_demo_state_not_enabled(client):
    """Without demo_runner, /demo/state returns 404."""
    resp = client.get("/demo/state")
    assert resp.status_code == 404


def test_demo_control_not_enabled(client):
    resp = client.post("/demo/control", json={"action": "pause"})
    assert resp.status_code == 404


def test_demo_state_enabled(tmp_path):
    from valg.demo import DemoRunner
    runner = DemoRunner()
    app = create_app(
        db_path=tmp_path / "v.db",
        data_dir=tmp_path / "data",
        demo_runner=runner,
        data_repo=tmp_path / "repo",
    )
    app.config["TESTING"] = True
    with app.test_client() as c:
        resp = c.get("/demo/state")
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert data["enabled"] is True
        assert data["state"] == "idle"
        assert "Election Night" in data["scenarios"]


def test_demo_control_set_speed(tmp_path):
    from valg.demo import DemoRunner
    runner = DemoRunner()
    app = create_app(
        db_path=tmp_path / "v.db",
        data_dir=tmp_path / "data",
        demo_runner=runner,
        data_repo=tmp_path / "repo",
    )
    app.config["TESTING"] = True
    with app.test_client() as c:
        resp = c.post("/demo/control", json={"action": "set_speed", "speed": 5.0})
        assert resp.status_code == 200
        assert runner.speed == 5.0


def test_demo_control_unknown_action(tmp_path):
    from valg.demo import DemoRunner
    runner = DemoRunner()
    app = create_app(
        db_path=tmp_path / "v.db",
        data_dir=tmp_path / "data",
        demo_runner=runner,
        data_repo=tmp_path / "repo",
    )
    app.config["TESTING"] = True
    with app.test_client() as c:
        resp = c.post("/demo/control", json={"action": "explode"})
        assert resp.status_code == 400
```

**Step 2: Run to verify failure**

```bash
pytest tests/test_server.py::test_demo_state_not_enabled tests/test_server.py::test_demo_state_enabled -v
```
Expected: FAIL — `create_app` doesn't accept `demo_runner` or `data_repo` yet.

**Step 3: Implement**

Modify `create_app` signature in `valg/server.py`:

```python
def create_app(
    db_path: Path = _DEFAULT_DB,
    data_dir: Path = _DEFAULT_DATA,
    demo_runner=None,
    data_repo: Path | None = None,
) -> Flask:
```

Add at the end of `create_app`, before `return app`, replacing the `return app` line:

```python
    _demo_repo = data_repo

    if demo_runner is not None:
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
    else:
        @app.get("/demo/state")
        def demo_state_disabled():
            return "Demo mode not enabled", 404

        @app.post("/demo/control")
        def demo_control_disabled():
            return "Demo mode not enabled", 404

    return app
```

Also add `import os` at the top of `valg/server.py` if not already present.

Replace `main()` in `valg/server.py`:

```python
def main() -> None:
    import argparse
    import os

    parser = argparse.ArgumentParser(prog="valg-server")
    parser.add_argument("--demo", action="store_true", help="Enable demo mode")
    parser.add_argument("--db", type=Path, default=_DEFAULT_DB)
    parser.add_argument("--port", type=int, default=5000)
    args = parser.parse_args()

    from valg.plugins import load_plugins
    load_plugins()

    db_path = args.db
    data_dir = _DEFAULT_DATA
    data_repo = Path(os.environ.get("VALG_DATA_REPO", "../valg-data"))

    demo_runner = None
    if args.demo:
        from valg.demo import DemoRunner
        demo_runner = DemoRunner()

    t = threading.Thread(target=_sync_loop, args=(data_dir, db_path), daemon=True)
    t.start()

    threading.Timer(1.0, lambda: webbrowser.open(f"http://localhost:{args.port}")).start()
    app = create_app(
        db_path=db_path,
        data_dir=data_dir,
        demo_runner=demo_runner,
        data_repo=data_repo,
    )
    app.run(host="127.0.0.1", port=args.port)
```

**Step 4: Run tests**

```bash
pytest tests/test_server.py -v
```
Expected: all passing including the 4 new demo tests.

**Step 5: Commit**

```bash
git add valg/server.py tests/test_server.py
git commit -m "feat(demo): /demo/state and /demo/control endpoints"
```

---

### Task 7: Browser demo control strip

**Files:**
- Modify: `valg/server.py` (the `_HTML` constant)

No automated tests — verify manually.

**Step 1: Add demo bar CSS**

Inside the `<style>` block in `_HTML`, append after the existing styles:

```css
  #demo-bar { padding: 10px 20px; background: #0d1117; border-bottom: 1px solid #30363d;
              display: none; align-items: center; gap: 10px; flex-wrap: wrap; font-size: 0.85em; }
  #demo-bar.visible { display: flex; }
  #demo-bar select { background: #21262d; color: #c9d1d9; border: 1px solid #30363d;
                     padding: 5px 8px; font-family: monospace; font-size: 0.85em; }
  .speed-btn { padding: 4px 10px; }
  .speed-btn.active { background: #1f6feb; border-color: #1f6feb; color: #fff; }
  #demo-step { color: #8b949e; font-size: 0.8em; margin-left: 8px; }
```

**Step 2: Add demo bar HTML**

After the `</div>` closing the `<div id="controls">` block and before `<div id="output-bar">`, insert:

```html
<div id="demo-bar">
  <span style="color:#58a6ff;font-weight:bold">DEMO</span>
  <select id="demo-scenario-select"></select>
  <button id="demo-start-btn" onclick="demoStartPause()">▶ Start</button>
  <button onclick="demoControl('restart')">↺ Restart</button>
  <span style="color:#8b949e">Speed:</span>
  <button class="speed-btn" data-speed="1"  onclick="demoSetSpeed(1)">1×</button>
  <button class="speed-btn" data-speed="2"  onclick="demoSetSpeed(2)">2×</button>
  <button class="speed-btn" data-speed="5"  onclick="demoSetSpeed(5)">5×</button>
  <button class="speed-btn" data-speed="60" onclick="demoSetSpeed(60)">60×</button>
  <span id="demo-step"></span>
</div>
```

**Step 3: Add demo JS**

Before the closing `</script>` tag, add:

```javascript
let _demoState = null;
let _prevStepIndex = null;

async function pollDemo() {
  try {
    const resp = await fetch('/demo/state');
    if (resp.status === 404) return;
    const s = await resp.json();
    _demoState = s;
    document.getElementById('demo-bar').classList.add('visible');

    // Populate scenario picker once
    const sel = document.getElementById('demo-scenario-select');
    if (sel.options.length === 0) {
      s.scenarios.forEach(name => {
        const opt = document.createElement('option');
        opt.value = opt.textContent = name;
        sel.appendChild(opt);
      });
      sel.onchange = () => demoControl('set_scenario', {scenario: sel.value});
    }
    sel.value = s.scenario;
    sel.disabled = s.state === 'running';

    // Start/Pause button label
    const btn = document.getElementById('demo-start-btn');
    if (s.state === 'idle' || s.state === 'done') btn.textContent = '▶ Start';
    else if (s.state === 'running') btn.textContent = '⏸ Pause';
    else if (s.state === 'paused') btn.textContent = '▶ Resume';

    // Speed button highlight
    document.querySelectorAll('.speed-btn').forEach(b => {
      b.classList.toggle('active', parseFloat(b.dataset.speed) === s.speed);
    });

    // Step indicator
    document.getElementById('demo-step').textContent =
      s.step_index >= 0
        ? `Step ${s.step_index + 1}/${s.steps_total}: ${s.step_name}`
        : '';

    // Auto-refresh current view when a step completes
    if (_prevStepIndex !== null && s.step_index !== _prevStepIndex && _current) {
      run(_current.cmd);
    }
    _prevStepIndex = s.step_index;
  } catch(e) {}
}

function demoStartPause() {
  if (!_demoState) return;
  if (_demoState.state === 'idle' || _demoState.state === 'done') demoControl('start');
  else if (_demoState.state === 'running') demoControl('pause');
  else if (_demoState.state === 'paused') demoControl('resume');
}

async function demoControl(action, extra) {
  await fetch('/demo/control', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({action, ...(extra || {})}),
  });
  pollDemo();
}

function demoSetSpeed(multiplier) {
  demoControl('set_speed', {speed: multiplier});
}

setInterval(pollDemo, 3000);
pollDemo();
```

**Step 4: Manual verification**

```bash
cd /Users/madsschmidt/Documents/valg
python -m valg.server --demo
```

Open `http://localhost:5000`. Check:
- Demo bar is visible with scenario picker and buttons
- Click "▶ Start" → button changes to "⏸ Pause", step indicator updates
- Click "⏸ Pause" → button changes to "▶ Resume", loop stops advancing
- Click "▶ Resume" → loop continues
- Speed buttons highlight the active multiplier when clicked
- "↺ Restart" resets and starts over from step 0
- Current view (e.g. Status) auto-refreshes after each wave

**Step 5: Commit**

```bash
git add valg/server.py
git commit -m "feat(demo): browser demo control strip"
```

---

### Task 8: E2E test

**Files:**
- Create: `tests/e2e/test_demo_e2e.py`

**Step 1: Write test**

```python
# tests/e2e/test_demo_e2e.py
"""E2E: full Election Night scenario at 100× speed.

Verifies that the complete pipeline (fake files → git commit → SQLite) works
end-to-end and that the DB contains party vote data and final candidate results
after all waves complete.
"""
import subprocess
import time
from pathlib import Path

import pytest

from valg.demo import DemoRunner
from valg.models import get_connection, init_db


def _init_git_repo(path: Path) -> None:
    subprocess.run(["git", "init"], cwd=path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "ci@test"], cwd=path, capture_output=True)
    subprocess.run(["git", "config", "user.name", "CI"], cwd=path, capture_output=True)
    (path / "README.md").write_text("demo data repo")
    subprocess.run(["git", "add", "-A"], cwd=path, capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=path, capture_output=True)


def test_election_night_e2e(tmp_path):
    data_repo = tmp_path / "valg-data"
    data_repo.mkdir()
    _init_git_repo(data_repo)

    db_path = tmp_path / "valg.db"
    conn = get_connection(db_path)
    init_db(conn)

    runner = DemoRunner()
    runner.set_speed(100.0)
    runner.start(db_path=db_path, data_repo=data_repo)

    deadline = time.time() + 25
    while runner.state != "done" and time.time() < deadline:
        time.sleep(0.3)

    assert runner.state == "done", f"Did not finish in time (state={runner.state})"
    assert runner.step_index == 5

    conn2 = get_connection(db_path)
    party_votes = conn2.execute("SELECT COUNT(*) FROM party_votes").fetchone()[0]
    assert party_votes > 0, "No party_votes — preliminary phase didn't process"

    final_results = conn2.execute(
        "SELECT COUNT(*) FROM results WHERE count_type='final'"
    ).fetchone()[0]
    assert final_results > 0, "No final results — fintælling phase didn't process"

    git_log = subprocess.run(
        ["git", "log", "--oneline"],
        cwd=data_repo, capture_output=True, text=True,
    ).stdout
    assert "demo:" in git_log, "No demo commits found in data repo git log"
```

**Step 2: Run**

```bash
pytest tests/e2e/test_demo_e2e.py -v
```
Expected: PASS (takes ~10–15 seconds).

**Step 3: Commit**

```bash
git add tests/e2e/test_demo_e2e.py
git commit -m "test(demo): E2E election night scenario"
```

---

### Task 9: Full suite + memory update

**Step 1: Run all tests**

```bash
pytest -v
```
Expected: all passing. Fix any regressions before proceeding.

**Step 2: Commit any fixes**

```bash
git add -p
git commit -m "fix(demo): address test regressions"
```

**Step 3: Update project memory**

Edit `/Users/madsschmidt/.claude/projects/-Users-madsschmidt-Documents/memory/MEMORY.md`:
- Update the `valg` status line to note that demo mode is implemented.
- Add a note about `valg/demo.py` (DemoRunner, SCENARIOS, Step) and the `--demo` server flag.
