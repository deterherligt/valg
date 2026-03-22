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
1. Under `_lock`, set `session.live = True` on every active session. Collect all runners.
2. Outside the lock, stop each runner (same pattern as `_stop_and_delete`: set `_stop_event`, set `_pause_event`, join thread with 5 s timeout). Do **not** delete session directories — sessions continue to exist so their cookies remain valid.

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

**`/demo/state` endpoint**: currently returns `session.runner.get_state_dict()` unconditionally when a session exists. Add check:
```python
if session is None or session.live:
    return jsonify({"enabled": False, "state": "unavailable", ...})
```
This ensures the frontend sees `demo.enabled = false` once the session has been switched to live, causing the header to flip from DEMO to LIVE.

**`_sync_loop()`**: after processing new files, check whether real preliminary results exist in the shared database:
```python
conn = get_connection(db_path)
has_real = conn.execute(
    "SELECT 1 FROM results WHERE count_type = 'preliminary' LIMIT 1"
).fetchone() is not None
```
If `has_real` and `session_manager` is not `None` and the switch has not already been triggered (`_live_data_available` is `False`), call `session_manager.switch_all_to_live()` and set the module-level flag `_live_data_available = True`.

The check runs on every sync iteration but `switch_all_to_live` is only called once because `_live_data_available` gates it.

**Module-level**: add `_live_data_available: bool = False` alongside the existing `_last_sync` and `_just_synced` globals.

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
_sync_loop runs every 60 s
  → sync_from_github
  → process_directory (shared db)
  → SELECT 1 FROM results WHERE count_type='preliminary'
  → if found and not _live_data_available:
      session_manager.switch_all_to_live()
      _live_data_available = True

Client polls /api/status every 10 s
  → just_synced → _fetchAll()
  → /demo/state: session.live → enabled=false
  → Alpine demo.enabled = false → header flips DEMO→LIVE
  → _get_conn() returns shared db → live data visible
```

---

## Testing

- **`switch_all_to_live` stops runners**: two sessions running, call `switch_all_to_live`, assert both `session.live == True` and both runners' `_stop_event` is set.
- **`_get_conn` uses shared db after live switch**: session with `live=True` — assert the returned connection path is the shared `db_path`, not the session `db_path`.
- **`/demo/state` returns `enabled=false` after live switch**: session with `live=True` — assert endpoint returns `{"enabled": false}`.
- **`_sync_loop` triggers switch once**: mock `session_manager.switch_all_to_live`; run sync twice with preliminary results present; assert it was called exactly once.
- **Header CSS in isolation**: no automated tests — visual correctness verified manually.

---

## Out of Scope

- Notifying the user visually when the switch happens (no toast/banner — silent transition by design).
- Switching sessions back from live to demo.
- Changing the demo control bar (scenario/pause/speed) layout.
- Per-session `switch_to_live` — the switch is always global (all sessions at once).
