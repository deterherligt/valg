# Demo Control Bar Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a demo control bar below the header in the valg dashboard that lets operators control demo scenarios (start/pause/resume/restart/speed/scenario) from the browser.

**Architecture:** Pure frontend change — three static files only. `app.js` gains a `demo` state object, a 5s polling loop for `/demo/state`, and four control methods. `index.html` gets the bar HTML (hidden when `demo.enabled` is false). `app.css` gets the bar and badge styles. No backend changes.

**Tech Stack:** Alpine.js v3 (already loaded via CDN), vanilla `fetch`, existing `/demo/state` (GET) and `/demo/control` (POST) endpoints.

**Spec:** `docs/superpowers/specs/2026-03-21-demo-control-bar-design.md`

---

## File map

| File | Change |
|------|--------|
| `valg/static/app.js` | Add `demo` state, `_fetchDemoState`, `demoControl`, `demoSetScenario`, `demoSetSpeed`, wire into `init()` |
| `valg/templates/index.html` | Add demo bar HTML between `</header>` and `<div class="columns">` |
| `valg/static/app.css` | Add `.demo-bar` and `.demo-badge--*` styles |
| `tests/test_server.py` | Add test verifying `/demo/state` response includes `scenario` and `scenarios` fields (contract test for frontend) |

---

## Chunk 1: Backend contract test + JS methods

### Task 1: Verify `/demo/state` response shape matches what the frontend expects

The frontend reads `demo.scenario` and `demo.scenarios` from the response. Confirm these fields exist.

**Files:**
- Modify: `tests/test_server.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_server.py`:

```python
def test_demo_state_has_scenario_and_scenarios_fields(tmp_path):
    """Frontend demo bar needs scenario (current) and scenarios (list) fields."""
    from valg.demo import DemoRunner
    app = create_app(
        db_path=tmp_path / "v.db",
        data_dir=tmp_path / "data",
        demo_runner=DemoRunner(),
        data_repo=tmp_path / "repo",
    )
    app.config["TESTING"] = True
    with app.test_client() as c:
        resp = c.get("/demo/state")
    assert resp.status_code == 200
    data = resp.get_json()
    assert "scenario" in data          # current scenario name (string)
    assert "scenarios" in data         # list of available scenario names
    assert isinstance(data["scenarios"], list)
    assert len(data["scenarios"]) > 0
    assert "speed" in data             # float — used by speed selector
    assert "enabled" in data           # bool — controls bar visibility
    assert "state" in data             # "idle"|"running"|"paused"|"done"
```

- [ ] **Step 2: Run test — expect PASS (contract already satisfied)**

```bash
source .venv/bin/activate && pytest tests/test_server.py::test_demo_state_has_scenario_and_scenarios_fields -v
```
Expected: PASS. This test documents the contract; if it fails, the backend has regressed.

- [ ] **Step 3: Commit**

```bash
git add tests/test_server.py
git commit -m "test(demo): add contract test for /demo/state response shape"
```

---

### Task 2: Add demo state and methods to `app.js`

**Files:**
- Modify: `valg/static/app.js`

- [ ] **Step 1: Add `demo` property to the Alpine data object**

In `valg/static/app.js`, the Alpine data object starts at line 2. Add `demo` after the existing `syncing` property (around line 17):

```js
demo: { enabled: false, state: 'idle', scenario: '', scenarios: [], speed: 1 },
```

- [ ] **Step 2: Wire `_fetchDemoState` into `init()`**

`init()` currently reads:
```js
async init() {
  await this._fetchAll()
  setInterval(() => this._poll(), 10000)
},
```

Change to:
```js
async init() {
  await this._fetchAll()
  await this._fetchDemoState()
  setInterval(() => this._poll(), 10000)
  setInterval(() => this._fetchDemoState(), 5000)
},
```

- [ ] **Step 3: Add the four demo methods**

Add these four methods to the Alpine data object, after `formatTime`:

```js
async _fetchDemoState() {
  const resp = await fetch('/demo/state').catch(() => null)
  if (!resp || !resp.ok) return
  this.demo = await resp.json()
},

async demoControl(action, extra = {}) {
  await fetch('/demo/control', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({action, ...extra}),
  }).catch(() => null)
  await this._fetchDemoState()
},

async demoSetScenario(name) {
  await this.demoControl('set_scenario', {scenario: name})
  await this.demoControl('restart')
},

async demoSetSpeed(speed) {
  await this.demoControl('set_speed', {speed: parseFloat(speed)})
},
```

- [ ] **Step 4: Run the full test suite**

```bash
source .venv/bin/activate && pytest tests/ -q --tb=short
```
Expected: all 259 tests pass. (JS changes have no effect on Python tests.)

- [ ] **Step 5: Commit**

```bash
git add valg/static/app.js
git commit -m "feat(demo-bar): add demo state polling and control methods to app.js"
```

---

## Chunk 2: HTML + CSS

### Task 3: Add demo bar HTML to `index.html`

**Files:**
- Modify: `valg/templates/index.html`

- [ ] **Step 1: Add the demo bar between `</header>` and `<div class="columns">`**

In `valg/templates/index.html`, find the line `  <!-- Three columns -->` (currently around line 25). Insert the demo bar immediately before it:

```html
  <!-- Demo control bar (only shown when demo mode is active) -->
  <div class="demo-bar" x-show="demo.enabled">
    <span class="demo-badge" :class="'demo-badge--' + demo.state" x-text="demo.state"></span>
    <select @change="demoSetScenario($event.target.value)">
      <template x-for="s in demo.scenarios" :key="s">
        <option :value="s" :selected="s === demo.scenario" x-text="s"></option>
      </template>
    </select>
    <button
      x-show="demo.state === 'running' || demo.state === 'paused'"
      @click="demoControl(demo.state === 'running' ? 'pause' : 'resume')"
      x-text="demo.state === 'running' ? '⏸ Pause' : '▶ Resume'">
    </button>
    <button @click="demoControl('restart')">↺ Restart</button>
    <select @change="demoSetSpeed($event.target.value)">
      <template x-for="s in [1,2,5,10,60]" :key="s">
        <option :value="s" :selected="parseFloat(demo.speed) === s" x-text="s + '×'"></option>
      </template>
    </select>
  </div>

```

- [ ] **Step 2: Run the full test suite**

```bash
source .venv/bin/activate && pytest tests/ -q --tb=short
```
Expected: all tests pass. (HTML change has no effect on Python tests.)

- [ ] **Step 3: Commit**

```bash
git add valg/templates/index.html
git commit -m "feat(demo-bar): add demo control bar HTML to index.html"
```

---

### Task 4: Add demo bar CSS to `app.css`

**Files:**
- Modify: `valg/static/app.css`

- [ ] **Step 1: Add demo bar styles**

In `valg/static/app.css`, add after the `.header` block (after the `@keyframes pulse` line, around line 28):

```css
/* ── Demo control bar ────────────────────────────────────────────── */
.demo-bar {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 14px;
  background: #1c2128;
  border-bottom: 1px solid #30363d;
  flex-shrink: 0;
  font-size: 0.85em;
}
.demo-bar select,
.demo-bar button {
  background: #21262d;
  border: 1px solid #30363d;
  border-radius: 4px;
  color: #c9d1d9;
  font-size: 0.85em;
  padding: 2px 8px;
  cursor: pointer;
}
.demo-bar button:hover { background: #30363d; }

.demo-badge {
  border-radius: 10px;
  padding: 1px 8px;
  font-size: 0.8em;
  font-weight: bold;
}
.demo-badge--running { background: #1f6feb; color: #fff; }
.demo-badge--paused  { background: #9e6a03; color: #e3b341; }
.demo-badge--done    { background: #30363d; color: #8b949e; }
.demo-badge--idle    { background: #30363d; color: #8b949e; }
```

- [ ] **Step 2: Run the full test suite**

```bash
source .venv/bin/activate && pytest tests/ -q --tb=short
```
Expected: all tests pass.

- [ ] **Step 3: Commit**

```bash
git add valg/static/app.css
git commit -m "feat(demo-bar): add demo bar and badge styles to app.css"
```

---

## Chunk 3: Manual smoke test

### Task 5: Verify in browser

- [ ] **Step 1: Start the server locally with demo mode**

```bash
source .venv/bin/activate && python -m valg.server
```

- [ ] **Step 2: Start a demo scenario via curl**

```bash
curl -s http://localhost:5000/demo/state
# Expected: {"enabled": true, "state": "idle", ...}

curl -s -X POST http://localhost:5000/demo/control \
  -H "Content-Type: application/json" \
  -d '{"action": "set_scenario", "scenario": "kv2025"}'

curl -s -X POST http://localhost:5000/demo/control \
  -H "Content-Type: application/json" \
  -d '{"action": "start"}'
```

- [ ] **Step 3: Open http://localhost:5000 in a browser**

Verify:
- Demo bar appears below the header
- State badge shows `running` in blue
- Scenario selector shows `kv2025` selected
- Pause button is visible; clicking it changes badge to `paused` (amber) and button to `▶ Resume`
- Restart button resets the scenario
- Speed selector changes speed (verify via `curl -s http://localhost:5000/demo/state | grep speed`)
- Bar disappears if demo is disabled

- [ ] **Step 4: Final test run**

```bash
source .venv/bin/activate && pytest tests/ -q --tb=short
```
Expected: all 259 tests pass.
