# Demo/Live Header Indicator & Auto-Exit Design

**Date:** 2026-03-22
**Scope:** (1) Show a persistent DEMO/LIVE status badge in the header so it is always clear whether the dashboard is showing simulated or real data. (2) Automatically switch all active demo sessions to live data the moment the first real election-night results arrive in the shared database.

---

## Problem

The current demo bar is only visible when `demo.enabled` is true and contains no signal about whether live data exists. A visitor has no persistent indication of which data source they are looking at. On election night, demo sessions need to transition to live data automatically without the visitor having to do anything.

---

## Design

### `valg/sessions.py` — `SessionState` and `SessionManager`

**`SessionState`**: add one field:
- `live: bool = False` — when `True`, this session has been switched to the shared database; its demo runner is stopped and should not be restarted.

**`SessionManager.switch_all_to_live()`**: new public method.
1. Under `_lock`, set `session.live = True` on every active session. Collect all runners into a local list.
2. Outside the lock, stop each runner using the same sequence as `_stop_and_delete` — set `_stop_event`, set `_pause_event` (unblocks if paused), join thread with 5 s timeout — but do **not** call `shutil.rmtree`. Sessions continue to exist so their cookies remain valid.

### `valg/server.py`

**`_get_conn()`**: add one branch. Current logic:
```
conn_path = session.db_path if session is not None else db_path
```
Change to:
```
conn_path = db_path if (session is None or session.live) else session.db_path
```
When `session.live` is `True`, reads come from the shared database and the visitor sees live results.

**`/demo/state` endpoint**: the current `session_manager` branch at `server.py:224-234` has:
```python
if session is None:
    return jsonify({"enabled": False, "state": "unavailable", ...})
return jsonify(session.runner.get_state_dict())
```
Change `if session is None:` to `if session is None or session.live:`. No other change. This ensures the frontend sees `demo.enabled = false` once the session has been switched to live, causing the header to flip from DEMO to LIVE.

**`_sync_loop()`**: add `session_manager=None` parameter and update the call in `main()`:
```python
# server.py:407 — change from:
t = threading.Thread(target=_sync_loop, args=(data_dir, db_path), daemon=True)
# to:
t = threading.Thread(target=_sync_loop, args=(data_dir, db_path, 60, session_manager), daemon=True)
```

Inside `_sync_loop`, after `process_directory`, add:
```python
global _live_data_available
if session_manager is not None and not _live_data_available:
    conn = get_connection(db_path)
    has_real = conn.execute(
        "SELECT 1 FROM results WHERE count_type = 'preliminary' LIMIT 1"
    ).fetchone() is not None
    conn.close()
    if has_real:
        session_manager.switch_all_to_live()
        _live_data_available = True
```

The `global _live_data_available` declaration is required (mirroring `global _last_sync, _just_synced` already in the function). The check runs on every sync iteration but `switch_all_to_live` is only called once because `_live_data_available` gates it.

**Module-level**: add `_live_data_available: bool = False` alongside the existing `_last_sync` and `_just_synced` globals. The full updated `_sync_loop` signature is:
```python
def _sync_loop(data_dir: Path, db_path: Path, interval: int = 60, session_manager=None) -> None:
```

### `valg/templates/index.html`

Replace the `.meta` span (currently shows "Synced X · N/M districts") with a conditional status indicator:

**Demo state** (`demo.enabled` is `true`):
```html
<span class="badge badge--demo">DEMO</span>
<span>Simulerede data · live ikke tilgængeligt endnu</span>
```

**Live state** (`demo.enabled` is `false`):
```html
<span class="badge badge--live">
  <span class="badge-dot"></span>LIVE
</span>
<span x-text="lastSynced ? 'Opdateret ' + lastSynced : 'Venter på sync…'"></span>
<span x-show="districtsTotal > 0">
  &bull; <span x-text="(districtsReported || 0) + '/' + (districtsTotal || 0) + ' kredse'"></span>
</span>
```

The `.meta` span keeps its existing `pulsing` class binding (`{'pulsing': syncing}`). The "Opdateret" live text replaces the current English "Synced" to match the badge Danish. "districts" → "kredse" likewise.

The demo control bar (`x-show="demo.enabled"`) is unchanged — it still shows scenario/pause/speed controls in demo mode and disappears when live.

### `valg/static/app.js`

`_fetchDemoState` runs every 5 s. When it detects `demo.enabled` flipping from `true` to `false` (the live switch), it must immediately refresh the data panels so the visitor sees live data without waiting for the next `_poll()` cycle. Change `_fetchDemoState` from:
```javascript
async _fetchDemoState() {
  const resp = await fetch('/demo/state').catch(() => null)
  if (!resp || !resp.ok) return
  this.demo = await resp.json()
},
```
To:
```javascript
async _fetchDemoState() {
  const resp = await fetch('/demo/state').catch(() => null)
  if (!resp || !resp.ok) return
  const wasDemo = this.demo.enabled
  this.demo = await resp.json()
  if (wasDemo && !this.demo.enabled) await this._fetchAll()
},
```
The `wasDemo && !this.demo.enabled` condition fires exactly once — when the session transitions from demo to live. Subsequent calls find `wasDemo = false` and skip the refresh.

### `valg/static/app.css`

Add badge styles near the existing `.demo-badge` rules:

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

---

## Data Flow

```
_sync_loop(data_dir, db_path, interval=60, session_manager=None)
  → sync_from_github
  → process_directory (shared db)
  → if session_manager and not _live_data_available:
      SELECT 1 FROM results WHERE count_type='preliminary'
      → if found:
          session_manager.switch_all_to_live()  # sets session.live=True, stops runners
          _live_data_available = True

Client _fetchDemoState runs every 5 s
  → GET /demo/state
  → session.live=True → enabled=false
  → wasDemo && !demo.enabled → _fetchAll() triggered immediately
  → header flips DEMO→LIVE, data panels refresh from shared db
```

---

## Testing

- **`switch_all_to_live` stops runners**: two sessions with running DemoRunners, call `switch_all_to_live`, assert both `session.live == True`, both runners' `_stop_event` is set (signalled), and both runner threads are no longer alive.
- **`_get_conn` uses shared db after live switch**: session with `live=True` — assert the returned connection path is the shared `db_path`, not the session `db_path`.
- **`/demo/state` returns `enabled=false` after live switch**: session with `live=True` — assert endpoint returns `{"enabled": false}`.
- **`_sync_loop` triggers switch once**: mock `session_manager.switch_all_to_live`; call the sync check logic twice with preliminary results present in the shared db; assert `switch_all_to_live` was called exactly once (gated by `_live_data_available`).
- **Header CSS in isolation**: no automated tests — visual correctness verified manually.

---

## Out of Scope

- Notifying the user visually when the switch happens (no toast/banner — silent transition by design).
- Switching sessions back from live to demo.
- Changing the demo control bar (scenario/pause/speed) layout.
- Per-session `switch_to_live` — the switch is always global (all sessions at once).
