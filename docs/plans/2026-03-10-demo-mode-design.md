# Demo Mode — Design Document

**Date:** 2026-03-10
**Scope:** Interactive demo mode for exploratory testing of the full data pipeline
**Status:** Approved

---

## Problem

The existing `sync --fake --wave N` command processes a single wave manually into a temp
directory and does not git-commit to the data repo. There is no way to run through a full
simulated election night end-to-end (write → commit → process → browser update) without
scripting it by hand.

Demo mode must exercise the same pipeline as a real election night:
fake files written to `valg-data/` → git committed → processed into `valg.db` → browser
refreshes automatically. Controls (speed, pause, restart) live in the browser UI.

---

## Architecture

```
[ DemoRunner (valg/demo.py) ]
       |
       |-- holds current Scenario
       |-- runs wave loop in background thread
       |-- writes files → commits data repo → processes into DB
       |-- exposes state: wave, paused, speed, scenario name
       v
[ server.py ]
       |-- GET  /demo/state      → JSON state snapshot
       |-- POST /demo/control    → start / pause / resume / restart / set_speed / set_scenario
       v
[ browser HTML ]
       |-- demo control strip (Start, Pause/Resume, Restart, speed, scenario picker)
       |-- polls /demo/state every 3s, updates strip labels
       |-- auto-refreshes current view after each wave completes
```

---

## Scenario System

A scenario is a list of **steps**. Each step is a named unit of work with:

- `name: str` — human-readable label shown in the browser ("Wave 1 — 25% districts")
- `wave: int` — which `fake_fetcher.write_wave` call to make (or `None` for setup-only steps)
- `setup: bool` — if True, also calls `fake_fetcher.setup_db` and clears existing data
- `process: bool` — if True, process written files into DB after writing (default True)
- `commit: bool` — if True, git-commit the data repo after writing (default True)
- `base_interval_s: float` — how long to sleep after this step at 1× speed

```python
# valg/demo.py

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
```

Scenarios are registered in a dict. New scenarios are added by appending to `SCENARIOS`
— no other files need to change.

### Built-in scenario: Election Night

```
Step 0 — Setup          wave=0, setup=True, process=False, commit=True, interval=0
Step 1 — 25% foreløbig  wave=1, interval=60s
Step 2 — 50% foreløbig  wave=2, interval=60s
Step 3 — 100% foreløbig wave=3, interval=60s
Step 4 — 50% fintælling wave=4, interval=60s
Step 5 — 100% fintælling wave=5, interval=60s
```

At 1× speed (max): 5 × 60s = 5 minutes total.
Speed multiplier slows intervals: 2× → 10 min, 5× → 25 min, 60× → realtime (~5 hrs).

Speed is a float multiplier applied to each step's `base_interval_s`:
`sleep_time = step.base_interval_s * speed_multiplier`

---

## DemoRunner

```python
class DemoRunner:
    scenario: Scenario
    speed: float          # multiplier, 1.0 = max speed (60s intervals)
    paused: bool
    step_index: int       # current step (0 = not started, -1 = done)
    state: str            # 'idle' | 'running' | 'paused' | 'done'

    def start(scenario_name: str, db_path: Path, data_repo: Path) -> None
    def pause() -> None
    def resume() -> None
    def restart() -> None   # clears DB + data repo demo folder, resets to step 0
    def set_speed(multiplier: float) -> None
    def set_scenario(name: str) -> None  # only valid when idle or after restart
```

The runner lives as a module-level singleton in `demo.py`, initialized when the server
starts in demo mode. Thread safety: a single `threading.Event` for pause/resume,
standard lock for state reads.

### Restart behaviour

On restart:
1. Stop the running loop (set a stop flag, wait for the thread to exit)
2. Drop and recreate all SQLite tables (`init_db` with `drop=True`)
3. Delete the demo folder from `valg-data/` (the synthetic election folder, not the whole repo)
4. Git-commit the deletion ("demo reset")
5. Re-run step 0 (setup)
6. Resume normal loop

---

## API endpoints

Added to `server.py`:

```
GET  /demo/state
→ { "enabled": bool, "state": "idle|running|paused|done",
    "scenario": "Election Night", "step_index": 2, "step_name": "50% foreløbig",
    "steps_total": 6, "speed": 1.0, "scenarios": ["Election Night", ...] }

POST /demo/control
Body: { "action": "start" | "pause" | "resume" | "restart" | "set_speed" | "set_scenario",
        "speed": 2.0,          // for set_speed
        "scenario": "name" }   // for set_scenario
→ 200 OK or 400 with error message
```

The server only exposes these endpoints when started in demo mode
(`python -m valg.server --demo`). Without `--demo`, they return 404.

---

## Browser UI changes

A demo control strip is injected into `_HTML` below the existing controls bar,
visible only when `/demo/state` reports `enabled: true`.

```
[ Scenario: Election Night ▾ ]  [ ▶ Start ]  [ ⏸ Pause ]  [ ↺ Restart ]
[ Speed: 1× ]  [ 2× ]  [ 5× ]  [ 60× ]   Step 2/6: 50% foreløbig
```

- Scenario picker: dropdown, only enabled when `state == 'idle'`
- Start/Pause/Resume: single button that toggles label based on state
- Restart: always enabled when demo is running or done
- Speed buttons: highlight active multiplier, clickable any time (takes effect next interval)
- Step indicator: "Step N/M: <step name>" updates every poll cycle
- After each wave completes (`step_index` increments), the browser auto-refreshes
  the currently active view command (same as the `just_synced` mechanic already in place)

Polling: the existing `pollSync` call is extended to also poll `/demo/state` every 3s
when demo mode is enabled.

---

## Data isolation

The demo writes to a dedicated subfolder within `valg-data/`:

```
valg-data/
  FV2024-demo/           ← synthetic election folder
    Geografi/
    Kandidatdata/
    Valgresultater/
    ...
```

This folder is created on start and deleted on restart. It does not interfere with
real election data that might be in the same repo. The processor is pointed at this
folder only.

---

## Starting demo mode

```bash
python -m valg.server --demo
```

This starts the Flask server with demo endpoints enabled and opens the browser.
The demo does not auto-start — the user clicks Start in the browser.

Optionally, the demo DB can be isolated from the main DB:

```bash
python -m valg.server --demo --db valg-demo.db
```

---

## Testing

- `tests/test_demo.py` — unit tests for `DemoRunner`: start/pause/resume/restart state
  transitions, speed multiplier applied to sleep time, restart clears state correctly
- `tests/e2e/test_demo_e2e.py` — runs the full Election Night scenario at speed 100×
  (0.6s intervals), asserts that DB has party votes after step 3 and candidate votes
  after step 5

---

## Out of scope

- Scenarios that pull from real historical SFTP archives (possible v2 — scenario steps
  could call a different data source)
- Scenario editor in the browser (scenarios are defined in Python for now)
- Multiple simultaneous demo instances
