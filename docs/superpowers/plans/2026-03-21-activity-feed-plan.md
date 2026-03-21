# Activity Feed + Place Drill-down Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the bottom event strip with a scrollable panel of all reporting polling places, and add a "Sted" drill-down tab in the right detail panel showing party and candidate votes for any selected place.

**Architecture:** New query functions in `queries.py` back two new Flask endpoints. The frontend replaces `_fetchFeed`/`feed` state with `_fetchFeedPlaces`/`feedItems`, adds a `selectedPlaceId` state + `placeDetail`, and renders a resizable bottom panel plus a Sted tab in the right column.

**Tech Stack:** Python/Flask, SQLite, Alpine.js, vanilla JS drag API, CSS flex

**Spec:** `docs/superpowers/specs/2026-03-21-activity-feed-design.md`

---

## File Map

| File | Change |
|------|--------|
| `valg/models.py` | Add `idx_events_type_id` index |
| `valg/queries.py` | Add `query_feed_places`, `query_place_detail`; remove `query_api_feed` |
| `valg/server.py` | Add `/api/feed/places`, `/api/place/<id>`; remove `/api/feed` |
| `valg/templates/index.html` | Replace feed strip with panel; add Sted tab; add column drag handles |
| `valg/static/app.js` | Replace feed state/methods; add place selection, Sted tab, resize handlers |
| `valg/static/app.css` | Replace feed strip styles; add panel, Sted tab, drag handle styles |
| `tests/test_server.py` | Replace 3 `/api/feed` tests with 7 new tests |

---

## Task 1: Add DB index

**Files:**
- Modify: `valg/models.py`

- [ ] **Step 1: Add the index to SCHEMA**

In `valg/models.py`, append to the `SCHEMA` string (after the existing `idx_events_type_time` line):

```python
CREATE INDEX IF NOT EXISTS idx_events_type_id ON events(event_type, id);
```

- [ ] **Step 2: Verify schema applies cleanly**

```bash
pytest tests/ -x -q
```

Expected: all existing tests pass.

- [ ] **Step 3: Commit**

```bash
git add valg/models.py
git commit -m "feat: add idx_events_type_id for cursor-paginated feed queries"
```

---

## Task 2: `query_feed_places`

**Files:**
- Modify: `valg/queries.py`
- Modify: `tests/test_server.py`

> **Background:** `events` stores `district_reported` events. `subject` = the afstemningsomraade `id` (TEXT, e.g. `"AO1"`). `description` = `"preliminary results"` or `"final results"`. The test generator (`generate_election` / `load_into_db`) does NOT create events — insert them manually in tests.

- [ ] **Step 1: Write failing tests**

In `tests/test_server.py`, add a new fixture and three tests. Add after the existing fixtures:

```python
@pytest.fixture
def client_with_events(tmp_path):
    db = tmp_path / "test.db"
    conn = get_connection(str(db))
    init_db(conn)
    e = generate_election(seed=42)
    load_into_db(conn, e, phase="preliminary")
    # Manually insert district_reported events
    ao_ids = [ao["id"] for ao in e["afstemningsomraader"]]
    for i, ao_id in enumerate(ao_ids[:3]):
        conn.execute(
            "INSERT INTO events (occurred_at, event_type, subject, description) "
            "VALUES (?,?,?,?)",
            (f"2024-11-05T21:0{i}:00", "district_reported", ao_id, "preliminary results"),
        )
    conn.commit()
    conn.close()
    app = create_app(db_path=db, data_dir=tmp_path / "data")
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c
```

Then add the tests:

```python
def test_feed_places_empty(client):
    resp = client.get("/api/feed/places")
    assert resp.status_code == 200
    assert resp.get_json() == []


def test_feed_places_returns_newest_first(client_with_events):
    resp = client_with_events.get("/api/feed/places")
    assert resp.status_code == 200
    data = resp.get_json()
    assert len(data) == 3
    # newest first (highest event id first)
    assert data[0]["occurred_at"] > data[-1]["occurred_at"]
    item = data[0]
    assert "event_id" in item
    assert "name" in item          # place name from afstemningsomraader
    assert "count_type" in item    # "foreløbig" or "fintælling"
    assert "occurred_at" in item
    assert item["count_type"] == "foreløbig"


def test_feed_places_cursor_pagination(client_with_events):
    # Get all 3, then fetch with before_id of the second item
    all_resp = client_with_events.get("/api/feed/places")
    all_data = all_resp.get_json()
    assert len(all_data) == 3
    second_id = all_data[1]["event_id"]
    page2 = client_with_events.get(f"/api/feed/places?before_id={second_id}")
    page2_data = page2.get_json()
    # Only entries older than second_id (id < second_id)
    assert len(page2_data) == 1
    assert all(item["event_id"] < second_id for item in page2_data)
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_server.py::test_feed_places_empty tests/test_server.py::test_feed_places_returns_newest_first tests/test_server.py::test_feed_places_cursor_pagination -v
```

Expected: FAIL (404 or AttributeError — endpoint doesn't exist yet).

- [ ] **Step 3: Implement `query_feed_places`**

Add to `valg/queries.py`:

```python
def query_feed_places(conn, before_id=None, limit: int = 50) -> list[dict]:
    params: list = ["district_reported"]
    where = "WHERE e.event_type = ?"
    if before_id is not None:
        where += " AND e.id < ?"
        params.append(before_id)
    params.append(limit)
    rows = conn.execute(
        f"""
        SELECT e.id AS event_id, ao.name, e.occurred_at, e.description
        FROM events e
        JOIN afstemningsomraader ao ON ao.id = e.subject
        {where}
        ORDER BY e.id DESC
        LIMIT ?
        """,
        params,
    ).fetchall()
    return [
        {
            "event_id": r["event_id"],
            "name": r["name"],
            "occurred_at": r["occurred_at"],
            "count_type": "fintælling" if "final" in r["description"] else "foreløbig",
        }
        for r in rows
    ]
```

- [ ] **Step 4: Add `/api/feed/places` to server.py**

In `valg/server.py`, add after the existing `api_feed` route:

```python
@app.get("/api/feed/places")
def api_feed_places():
    limit = min(int(request.args.get("limit", 50)), 200)
    before_id_raw = request.args.get("before_id")
    before_id = int(before_id_raw) if before_id_raw else None
    from valg.queries import query_feed_places
    return jsonify(query_feed_places(_get_conn(), before_id=before_id, limit=limit))
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
pytest tests/test_server.py::test_feed_places_empty tests/test_server.py::test_feed_places_returns_newest_first tests/test_server.py::test_feed_places_cursor_pagination -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add valg/queries.py valg/server.py tests/test_server.py
git commit -m "feat: add /api/feed/places endpoint with cursor pagination"
```

---

## Task 3: `query_place_detail`

**Files:**
- Modify: `valg/queries.py`
- Modify: `tests/test_server.py`

> **Background:** Returns the latest party votes and (if available) candidate votes for one `afstemningsomraade_id`. For delta: compare the two most recent distinct `snapshot_at` values. If both `preliminary` and `final` rows exist at the same `snapshot_at`, prefer `final` (ORDER BY count_type ASC — `'final' < 'preliminary'` lexicographically).

- [ ] **Step 1: Write failing tests**

Add to `tests/test_server.py`:

```python
def test_place_detail_one_snapshot_no_delta(client_with_data):
    # client_with_data has preliminary results loaded
    # Find an afstemningsomraade that has results
    from valg.models import get_connection, init_db
    e = generate_election(seed=42)
    ao_id = e["afstemningsomraader"][0]["id"]
    resp = client_with_data.get(f"/api/place/{ao_id}")
    assert resp.status_code == 200
    data = resp.get_json()
    assert "parties" in data
    assert "candidates" in data
    assert "name" in data
    assert "opstillingskreds" in data
    assert "count_type" in data
    assert "occurred_at" in data
    assert len(data["parties"]) > 0
    assert data["candidates"] == []  # no final data
    # Delta must be null for all parties (only one snapshot)
    for p in data["parties"]:
        assert p["delta"] is None


def test_place_detail_two_snapshots_has_delta(tmp_path):
    db = tmp_path / "test.db"
    conn = get_connection(str(db))
    init_db(conn)
    e = generate_election(seed=42)
    load_into_db(conn, e, phase="preliminary")
    # Insert a second preliminary snapshot with different snapshot_at
    ao = e["afstemningsomraader"][0]
    party_id = e["parties"][0]["id"]
    conn.execute(
        "INSERT OR IGNORE INTO results "
        "(afstemningsomraade_id, party_id, candidate_id, votes, count_type, snapshot_at) "
        "VALUES (?,?,NULL,999,'preliminary','2024-11-05T23:00:00')",
        (ao["id"], party_id),
    )
    conn.commit()
    conn.close()

    from valg.server import create_app
    app = create_app(db_path=db, data_dir=tmp_path / "data")
    app.config["TESTING"] = True
    with app.test_client() as c:
        resp = c.get(f"/api/place/{ao['id']}")
        data = resp.get_json()
    # At least one party should have a non-null delta
    deltas = [p["delta"] for p in data["parties"]]
    assert any(d is not None for d in deltas)


def test_place_detail_with_final_has_candidates(client_with_final_data):
    e = generate_election(seed=42)
    ao_id = e["afstemningsomraader"][0]["id"]
    resp = client_with_final_data.get(f"/api/place/{ao_id}")
    data = resp.get_json()
    assert len(data["candidates"]) > 0
    for c in data["candidates"]:
        assert "name" in c
        assert "party_letter" in c
        assert "votes" in c


def test_place_detail_not_found(client):
    resp = client.get("/api/place/nonexistent-id")
    assert resp.status_code == 404
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_server.py::test_place_detail_one_snapshot_no_delta tests/test_server.py::test_place_detail_two_snapshots_has_delta tests/test_server.py::test_place_detail_with_final_has_candidates tests/test_server.py::test_place_detail_not_found -v
```

Expected: FAIL.

- [ ] **Step 3: Implement `query_place_detail`**

Add to `valg/queries.py`:

```python
def query_place_detail(conn, place_id: str) -> dict | None:
    ao = conn.execute(
        "SELECT ao.id, ao.name, ok.name AS opstillingskreds "
        "FROM afstemningsomraader ao "
        "JOIN opstillingskredse ok ON ok.id = ao.opstillingskreds_id "
        "WHERE ao.id = ?",
        (place_id,),
    ).fetchone()
    if not ao:
        return None

    # Two most recent distinct snapshot_at values for this place
    snaps = conn.execute(
        "SELECT DISTINCT snapshot_at FROM results "
        "WHERE afstemningsomraade_id = ? AND candidate_id IS NULL "
        "ORDER BY snapshot_at DESC LIMIT 2",
        (place_id,),
    ).fetchall()
    if not snaps:
        return None

    latest_snap = snaps[0]["snapshot_at"]
    prev_snap = snaps[1]["snapshot_at"] if len(snaps) > 1 else None

    def _party_votes_at(snap_at: str) -> dict:
        """Return {party_id: votes} preferring 'final' over 'preliminary'."""
        rows = conn.execute(
            "WITH ranked AS ("
            "  SELECT party_id, votes, count_type, "
            "  ROW_NUMBER() OVER (PARTITION BY party_id ORDER BY count_type ASC) AS rn "
            "  FROM results "
            "  WHERE afstemningsomraade_id = ? AND snapshot_at = ? AND candidate_id IS NULL"
            ") SELECT party_id, votes, count_type FROM ranked WHERE rn = 1",
            (place_id, snap_at),
        ).fetchall()
        return {r["party_id"]: r for r in rows}

    latest_rows = _party_votes_at(latest_snap)
    prev_rows = _party_votes_at(prev_snap) if prev_snap else {}

    # Dominant count_type for header (prefer 'final')
    count_types = {r["count_type"] for r in latest_rows.values()}
    count_type_db = "final" if "final" in count_types else "preliminary"
    count_type_display = "fintælling" if count_type_db == "final" else "foreløbig"

    # Build party list with deltas
    party_meta = {
        r["id"]: r
        for r in conn.execute(
            "SELECT id, letter, name FROM parties WHERE id IN ("
            + ",".join("?" * len(latest_rows)) + ")",
            list(latest_rows.keys()),
        ).fetchall()
    } if latest_rows else {}

    parties = []
    for party_id, row in sorted(latest_rows.items(), key=lambda x: -x[1]["votes"]):
        meta = party_meta.get(party_id, {"letter": party_id, "name": party_id})
        prev = prev_rows.get(party_id)
        delta = (row["votes"] - prev["votes"]) if prev else None
        parties.append({
            "party_id": party_id,
            "letter": meta["letter"],
            "name": meta["name"],
            "votes": row["votes"],
            "delta": delta,
        })

    # Candidate votes (only present for 'final' count)
    cand_rows = conn.execute(
        "WITH ranked AS ("
        "  SELECT r.candidate_id, r.votes, c.name AS cand_name, p.letter AS party_letter, "
        "  ROW_NUMBER() OVER (PARTITION BY r.candidate_id ORDER BY r.count_type ASC) AS rn "
        "  FROM results r "
        "  JOIN candidates c ON c.id = r.candidate_id "
        "  JOIN parties p ON p.id = c.party_id "
        "  WHERE r.afstemningsomraade_id = ? AND r.snapshot_at = ? "
        "    AND r.candidate_id IS NOT NULL"
        ") SELECT candidate_id, votes, cand_name, party_letter FROM ranked WHERE rn = 1 "
        "ORDER BY votes DESC",
        (place_id, latest_snap),
    ).fetchall()

    candidates = [
        {"name": r["cand_name"], "party_letter": r["party_letter"], "votes": r["votes"]}
        for r in cand_rows
    ]

    return {
        "name": ao["name"],
        "opstillingskreds": ao["opstillingskreds"],
        "count_type": count_type_display,
        "occurred_at": latest_snap,
        "parties": parties,
        "candidates": candidates,
    }
```

- [ ] **Step 4: Add `/api/place/<id>` to server.py**

In `valg/server.py`, add after the `api_feed_places` route:

```python
@app.get("/api/place/<place_id>")
def api_place(place_id):
    from valg.queries import query_place_detail
    data = query_place_detail(_get_conn(), place_id)
    if data is None:
        return jsonify({"error": "not found"}), 404
    return jsonify(data)
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
pytest tests/test_server.py::test_place_detail_one_snapshot_no_delta tests/test_server.py::test_place_detail_two_snapshots_has_delta tests/test_server.py::test_place_detail_with_final_has_candidates tests/test_server.py::test_place_detail_not_found -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add valg/queries.py valg/server.py tests/test_server.py
git commit -m "feat: add /api/place/<id> endpoint with party/candidate drill-down"
```

---

## Task 4: Remove `/api/feed` and its tests

**Files:**
- Modify: `valg/server.py`
- Modify: `valg/queries.py`
- Modify: `tests/test_server.py`

- [ ] **Step 1: Delete the three old `/api/feed` tests**

In `tests/test_server.py`, remove these three functions entirely:
- `test_api_feed_returns_list`
- `test_api_feed_shape_when_events_exist`
- `test_api_feed_respects_limit`

- [ ] **Step 2: Remove the `/api/feed` route from server.py**

In `valg/server.py`, delete:

```python
@app.get("/api/feed")
def api_feed():
    limit = min(int(request.args.get("limit", 50)), 200)
    from valg.queries import query_api_feed
    return jsonify(query_api_feed(_get_conn(), limit))
```

- [ ] **Step 3: Remove `query_api_feed` from queries.py**

In `valg/queries.py`, delete:

```python
def query_api_feed(conn, limit: int = 50) -> list[dict]:
    rows = conn.execute(
        "SELECT occurred_at, description FROM events ORDER BY occurred_at DESC LIMIT ?",
        (limit,),
    ).fetchall()
    return [{"occurred_at": r["occurred_at"], "description": r["description"]} for r in rows]
```

- [ ] **Step 4: Run full test suite**

```bash
pytest tests/ -x -q
```

Expected: all pass (no reference to the removed endpoint).

- [ ] **Step 5: Commit**

```bash
git add valg/queries.py valg/server.py tests/test_server.py
git commit -m "remove /api/feed endpoint (replaced by /api/feed/places)"
```

---

## Task 5: Replace feed strip with resizable panel (HTML + CSS)

**Files:**
- Modify: `valg/templates/index.html`
- Modify: `valg/static/app.css`

> The current feed strip is a horizontal scrolling flex row at the bottom (`<div class="feed-strip">`). Replace it with a vertical scrollable panel. CSS sets an initial height; JS in Task 7 makes it resizable.

- [ ] **Step 1: Replace feed strip HTML**

In `valg/templates/index.html`, replace:

```html
  <!-- Feed strip -->
  <div class="feed-strip">
    <span class="feed-strip-label">Feed</span>
    <template x-if="feed.length === 0">
      <span class="feed-strip-empty">No events yet</span>
    </template>
    <template x-for="item in feed" :key="item.occurred_at + item.description">
      <span class="feed-strip-item"
            x-text="formatTime(item.occurred_at) + ' · ' + item.description">
      </span>
    </template>
  </div>
```

With:

```html
  <!-- Feed panel -->
  <div class="feed-panel" :style="'height:' + feedPanelHeight + 'px'">
    <div class="feed-panel-resize" @mousedown="startFeedResize($event)"></div>
    <div class="feed-panel-header">
      <span class="feed-panel-label">Indberetninger</span>
      <span class="feed-panel-count"
            x-text="(districtsReported || 0) + ' / ' + (districtsTotal || 0) + ' steder'">
      </span>
    </div>
    <div class="feed-panel-body" x-ref="feedBody">
      <template x-if="feedItems.length === 0">
        <div class="feed-panel-empty">Ingen indberetninger endnu</div>
      </template>
      <template x-for="item in feedItems" :key="item.event_id">
        <div class="feed-place-row"
             :class="{selected: selectedPlaceId === String(item.event_id)}"
             @click="selectPlace(item)">
          <span class="feed-place-name" x-text="item.name"></span>
          <span class="feed-place-type" x-text="item.count_type"></span>
          <span class="feed-place-time" x-text="formatTime(item.occurred_at)"></span>
        </div>
      </template>
      <template x-if="feedItems.length > 0 && !feedExhausted">
        <button class="feed-load-more" @click="_loadMorePlaces()">Vis ældre</button>
      </template>
    </div>
  </div>
```

- [ ] **Step 2: Replace feed strip CSS**

In `valg/static/app.css`, replace the `/* ── Feed strip ── */` block:

```css
/* ── Feed strip ──────────────────────────────────────────────────── */
.feed-strip {
  display: flex;
  align-items: center;
```

...through the closing `}` of `.feed-strip-empty` with:

```css
/* ── Feed panel ──────────────────────────────────────────────────── */
.feed-panel {
  flex-shrink: 0;
  border-top: 2px solid #58a6ff;
  background: #0d1117;
  display: flex;
  flex-direction: column;
  min-height: 52px;
  position: relative;
}
.feed-panel-resize {
  position: absolute;
  top: -4px;
  left: 0;
  right: 0;
  height: 8px;
  cursor: ns-resize;
  z-index: 10;
}
.feed-panel-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 4px 12px;
  background: #161b22;
  border-bottom: 1px solid #30363d;
  flex-shrink: 0;
}
.feed-panel-label { color: #8b949e; font-size: 0.8em; text-transform: uppercase; }
.feed-panel-count { color: #58a6ff; font-size: 0.8em; }
.feed-panel-body {
  flex: 1;
  overflow-y: auto;
  scrollbar-width: thin;
}
.feed-panel-empty { color: #8b949e; font-size: 0.85em; padding: 8px 12px; }
.feed-place-row {
  display: flex;
  gap: 8px;
  align-items: baseline;
  padding: 4px 12px;
  cursor: pointer;
  font-size: 0.88em;
  border-bottom: 1px solid #21262d;
}
.feed-place-row:hover { background: #161b22; }
.feed-place-row.selected { background: #1f2937; border-left: 2px solid #58a6ff; padding-left: 10px; }
.feed-place-name { color: #58a6ff; flex: 1; }
.feed-place-type { color: #8b949e; font-size: 0.85em; }
.feed-place-time { color: #484f58; font-size: 0.85em; }
.feed-load-more {
  width: 100%;
  padding: 6px;
  background: #161b22;
  border: none;
  border-top: 1px solid #30363d;
  color: #8b949e;
  cursor: pointer;
  font-size: 0.85em;
}
.feed-load-more:hover { color: #c9d1d9; }
```

- [ ] **Step 3: Verify the app loads without JS errors**

```bash
python -m valg.server --demo &
open http://localhost:5000
```

Check the bottom of the page: the panel should render (though clicking will fail until Task 6). Kill the server.

- [ ] **Step 4: Commit**

```bash
git add valg/templates/index.html valg/static/app.css
git commit -m "feat: replace feed strip with resizable panel (HTML+CSS)"
```

---

## Task 6: app.js — feed state and place selection

**Files:**
- Modify: `valg/static/app.js`

> Replace `feed: []` and `_fetchFeed()` with `feedItems`, `selectedPlaceId`, `placeDetail`, `_fetchFeedPlaces()`, `_loadMorePlaces()`, `selectPlace()`. The `_fetchFeed` call in `_poll` is replaced; `_fetchAll` is updated too.

- [ ] **Step 1: Update Alpine state and feed methods**

In `valg/static/app.js`, replace:

```javascript
    feed: [],
```

With:

```javascript
    feedItems: [],
    feedExhausted: false,
    selectedPlaceId: null,
    placeDetail: null,
    activeTab: 'detail',  // 'detail' | 'sted'
    feedPanelHeight: 120,
```

- [ ] **Step 2: Replace `_fetchFeed` with `_fetchFeedPlaces`**

Remove:

```javascript
    async _fetchFeed() {
      const resp = await fetch('/api/feed?limit=50').catch(() => null)
      if (!resp) return
      this.feed = await resp.json()
    },
```

Add in its place:

```javascript
    async _fetchFeedPlaces() {
      const resp = await fetch('/api/feed/places?limit=50').catch(() => null)
      if (!resp) return
      const data = await resp.json()
      this.feedItems = data
      this.feedExhausted = data.length < 50
      if (!this.selectedPlaceId) {
        this.$nextTick(() => {
          const body = this.$refs.feedBody
          if (body) body.scrollTop = 0
        })
      }
    },

    async _loadMorePlaces() {
      if (!this.feedItems.length) return
      const minId = Math.min(...this.feedItems.map(x => x.event_id))
      const resp = await fetch(`/api/feed/places?before_id=${minId}&limit=50`).catch(() => null)
      if (!resp) return
      const data = await resp.json()
      this.feedItems = [...this.feedItems, ...data]
      this.feedExhausted = data.length < 50
    },

    async selectPlace(item) {
      this.selectedPlaceId = String(item.event_id)
      this.activeTab = 'sted'
      const resp = await fetch('/api/place/' + encodeURIComponent(item.name.replace(/ /g,'_')) ).catch(() => null)
      // Note: /api/place/<id> takes the afstemningsomraade id, not event_id.
      // We need the place_id. Store it on the feedItem.
      // See Task 3 — we'll add place_id to the feed response there.
    },
```

**Correction:** The feed items need to include the `place_id` (afstemningsomraade id) so `selectPlace` can call `/api/place/<place_id>`. Update `query_feed_places` to include it.

- [ ] **Step 3: Add `place_id` to `query_feed_places` response**

In `valg/queries.py`, update `query_feed_places` to return `place_id`:

```python
    return [
        {
            "event_id": r["event_id"],
            "place_id": r["subject"],      # afstemningsomraade id
            "name": r["name"],
            "occurred_at": r["occurred_at"],
            "count_type": "fintælling" if "final" in r["description"] else "foreløbig",
        }
        for r in rows
    ]
```

Also update the SELECT to include `e.subject`:

```python
        f"""
        SELECT e.id AS event_id, e.subject, ao.name, e.occurred_at, e.description
        FROM events e
        JOIN afstemningsomraader ao ON ao.id = e.subject
        {where}
        ORDER BY e.id DESC
        LIMIT ?
        """,
```

- [ ] **Step 4: Fix `selectPlace` to use `place_id`**

Replace the placeholder `selectPlace` with:

```javascript
    async selectPlace(item) {
      this.selectedPlaceId = String(item.event_id)
      this.activeTab = 'sted'
      const resp = await fetch('/api/place/' + item.place_id).catch(() => null)
      if (!resp) return
      this.placeDetail = await resp.json()
    },
```

- [ ] **Step 5: Update `_fetchAll` and `_poll`**

In `_fetchAll`, replace `this._fetchFeed()` with `this._fetchFeedPlaces()`:

```javascript
    async _fetchAll() {
      await Promise.all([this._fetchStatus(), this._fetchParties(), this._fetchFeedPlaces()])
      // ... rest unchanged
    },
```

In `_poll`, replace the `_fetchFeed()` call in the non-just_synced branch:

```javascript
      await Promise.all([this._fetchParties(), this._fetchFeedPlaces()])
```

- [ ] **Step 6: Update the feed test to check for `place_id`**

In `tests/test_server.py`, update `test_feed_places_returns_newest_first`:

```python
    assert "place_id" in item   # afstemningsomraade id for /api/place/<id>
```

- [ ] **Step 7: Run the full test suite**

```bash
pytest tests/ -x -q
```

Expected: all pass.

- [ ] **Step 8: Commit**

```bash
git add valg/static/app.js valg/queries.py tests/test_server.py
git commit -m "feat: replace feed state with feedItems, selectPlace, _fetchFeedPlaces"
```

---

## Task 7: Sted tab in right detail panel

**Files:**
- Modify: `valg/templates/index.html`
- Modify: `valg/static/app.css`

> Add a tab bar to the right panel (Detaljer / Sted). "Sted" tab appears only when `placeDetail` is set. Clicking a place row sets `activeTab = 'sted'`.

- [ ] **Step 1: Add tab bar and Sted tab to right panel**

In `valg/templates/index.html`, find:

```html
    <!-- Right panel -->
    <div class="col col-detail">
      <div class="col-header">
        <span x-show="!focusedCandidateId">Details</span>
        <span x-show="focusedCandidateId && candidateDetail"
              x-text="candidateDetail ? candidateDetail.name + ' (' + candidateDetail.party_letter + ')' : ''">
        </span>
      </div>
      <div class="detail-body">
```

Replace with:

```html
    <!-- Right panel -->
    <div class="col col-detail">
      <div class="col-header" style="padding:0">
        <div class="detail-tabs">
          <button class="detail-tab"
                  :class="{active: activeTab !== 'sted'}"
                  @click="activeTab = 'detail'">
            <span x-show="!focusedCandidateId">Detaljer</span>
            <span x-show="focusedCandidateId && candidateDetail"
                  x-text="candidateDetail ? candidateDetail.name + ' (' + candidateDetail.party_letter + ')' : 'Detaljer'">
            </span>
          </button>
          <template x-if="placeDetail">
            <button class="detail-tab"
                    :class="{active: activeTab === 'sted'}"
                    @click="activeTab = 'sted'">
              Sted
            </button>
          </template>
        </div>
      </div>
      <div class="detail-body">
```

- [ ] **Step 2: Wrap existing detail content with `x-show`**

Directly after `<div class="detail-body">`, add:

```html
        <div x-show="activeTab !== 'sted'">
```

And close it before `</div><!-- /detail-body -->`:

```html
        </div><!-- /activeTab !== sted -->
```

(This wraps both existing `<!-- Party detail mode -->` and `<!-- Candidate detail mode -->` blocks.)

- [ ] **Step 3: Add Sted tab content after the closing `</div>` from step 2**

```html
        <!-- Sted tab -->
        <template x-if="activeTab === 'sted' && placeDetail">
          <div class="sted-detail">
            <div class="sted-header">
              <div class="sted-name" x-text="placeDetail.name"></div>
              <div class="sted-meta"
                   x-text="placeDetail.opstillingskreds + ' · ' + placeDetail.count_type + ' · ' + formatTime(placeDetail.occurred_at)">
              </div>
            </div>
            <div class="detail-section-label">Partistemmer</div>
            <table class="data-table">
              <thead><tr><th>Parti</th><th>Stemmer</th><th>Δ</th></tr></thead>
              <tbody>
                <template x-for="p in placeDetail.parties" :key="p.party_id">
                  <tr>
                    <td x-text="(p.letter || p.party_id) + ' ' + p.name"></td>
                    <td x-text="formatNum(p.votes)"></td>
                    <td :class="p.delta > 0 ? 'delta-pos' : 'null-votes'"
                        x-text="p.delta !== null ? (p.delta > 0 ? '+' : '') + formatNum(p.delta) : '—'">
                    </td>
                  </tr>
                </template>
              </tbody>
            </table>
            <div class="detail-section-label">Kandidatstemmer</div>
            <template x-if="placeDetail.candidates.length === 0">
              <div style="color:#8b949e;font-size:0.9em;padding:4px 0">
                Kandidatstemmer ikke tilgængeligt ved foreløbig optælling
              </div>
            </template>
            <template x-if="placeDetail.candidates.length > 0">
              <table class="data-table">
                <thead><tr><th>Kandidat</th><th>Parti</th><th>Stemmer</th></tr></thead>
                <tbody>
                  <template x-for="c in placeDetail.candidates" :key="c.name">
                    <tr>
                      <td x-text="c.name"></td>
                      <td x-text="c.party_letter"></td>
                      <td x-text="formatNum(c.votes)"></td>
                    </tr>
                  </template>
                </tbody>
              </table>
            </template>
          </div>
        </template>
```

- [ ] **Step 4: Add tab and Sted styles to app.css**

Add to `valg/static/app.css`:

```css
/* ── Detail tabs ─────────────────────────────────────────────────── */
.detail-tabs { display: flex; border-bottom: 1px solid #21262d; }
.detail-tab {
  padding: 6px 12px;
  background: none;
  border: none;
  border-bottom: 2px solid transparent;
  color: #8b949e;
  cursor: pointer;
  font-size: 0.85em;
}
.detail-tab.active { color: #c9d1d9; border-bottom-color: #58a6ff; }
.detail-tab:hover { color: #c9d1d9; }

/* ── Sted detail ─────────────────────────────────────────────────── */
.sted-detail { padding: 8px 12px; }
.sted-name { color: #e6edf3; font-weight: bold; margin-bottom: 2px; }
.sted-meta { color: #8b949e; font-size: 0.85em; margin-bottom: 8px; }
.delta-pos { color: #3fb950; text-align: right; }
```

- [ ] **Step 5: Smoke test**

```bash
python -m valg.server --demo &
open http://localhost:5000
```

Start the demo. When places report in, the feed panel should show them. Click a place — the Sted tab should appear and show party votes. Kill the server.

- [ ] **Step 6: Commit**

```bash
git add valg/templates/index.html valg/static/app.css
git commit -m "feat: add Sted drill-down tab in right detail panel"
```

---

## Task 8: Resizable feed panel and column widths

**Files:**
- Modify: `valg/static/app.js`
- Modify: `valg/templates/index.html`
- Modify: `valg/static/app.css`

> Feed panel: drag top edge to resize height. Columns: drag divider handles between the three columns to resize widths. All sizes persisted to `localStorage`.

- [ ] **Step 1: Add feed panel resize logic to app.js**

Add to the Alpine data object (alongside the other state fields):

```javascript
    _feedResizing: false,
    _feedResizeStartY: 0,
    _feedResizeStartH: 0,
```

Add methods:

```javascript
    startFeedResize(e) {
      this._feedResizing = true
      this._feedResizeStartY = e.clientY
      this._feedResizeStartH = this.feedPanelHeight
      const onMove = (ev) => {
        if (!this._feedResizing) return
        const delta = this._feedResizeStartY - ev.clientY
        this.feedPanelHeight = Math.max(52, this._feedResizeStartH + delta)
      }
      const onUp = () => {
        this._feedResizing = false
        localStorage.setItem('valg_feed_height', this.feedPanelHeight)
        document.removeEventListener('mousemove', onMove)
        document.removeEventListener('mouseup', onUp)
      }
      document.addEventListener('mousemove', onMove)
      document.addEventListener('mouseup', onUp)
    },
```

- [ ] **Step 2: Restore feed panel height from localStorage on init**

In the `init()` method, add at the start:

```javascript
      const savedH = localStorage.getItem('valg_feed_height')
      if (savedH) this.feedPanelHeight = parseInt(savedH, 10)
      const savedCols = localStorage.getItem('valg_col_widths')
      if (savedCols) {
        try {
          const w = JSON.parse(savedCols)
          this.colWidths = w
        } catch (_) {}
      }
```

Also add `colWidths: {parties: 220, candidates: 220}` to the Alpine state.

- [ ] **Step 3: Add column drag handles to index.html**

In `valg/templates/index.html`, add a drag handle div between each pair of columns:

After `</div><!-- /col-parties -->`:
```html
    <div class="col-resize-handle" @mousedown="startColResize($event, 'parties')"></div>
```

After `</div><!-- /col-candidates -->`:
```html
    <div class="col-resize-handle" @mousedown="startColResize($event, 'candidates')"></div>
```

Also bind widths on the column divs:

```html
    <div class="col col-parties" :style="'width:' + colWidths.parties + 'px; flex-shrink:0'">
    <div class="col col-candidates" :style="'width:' + colWidths.candidates + 'px; flex-shrink:0'">
```

- [ ] **Step 4: Add column resize logic to app.js**

```javascript
    startColResize(e, col) {
      const startX = e.clientX
      const startW = this.colWidths[col]
      const onMove = (ev) => {
        const delta = ev.clientX - startX
        this.colWidths[col] = Math.max(120, startW + delta)
      }
      const onUp = () => {
        localStorage.setItem('valg_col_widths', JSON.stringify(this.colWidths))
        document.removeEventListener('mousemove', onMove)
        document.removeEventListener('mouseup', onUp)
      }
      document.addEventListener('mousemove', onMove)
      document.addEventListener('mouseup', onUp)
    },
```

- [ ] **Step 5: Add drag handle CSS**

Add to `valg/static/app.css`:

```css
/* ── Column resize handles ───────────────────────────────────────── */
.col-resize-handle {
  width: 4px;
  background: transparent;
  cursor: col-resize;
  flex-shrink: 0;
  transition: background 0.15s;
}
.col-resize-handle:hover { background: #58a6ff44; }
```

Also update `.col-parties` and `.col-candidates` in the CSS — they currently have hardcoded widths. Remove those fixed widths so the `:style` binding in the HTML controls them:

Find and remove any lines like `width: 220px` from `.col-parties` and `.col-candidates` in `app.css`.

- [ ] **Step 6: Run full test suite**

```bash
pytest tests/ -x -q
```

Expected: all pass.

- [ ] **Step 7: Smoke test resize**

```bash
python -m valg.server --demo &
open http://localhost:5000
```

- Drag the top edge of the feed panel — it should resize
- Drag the divider between Partier and Kandidater — the columns should resize
- Refresh — sizes should be restored from localStorage
- Kill the server.

- [ ] **Step 8: Commit**

```bash
git add valg/templates/index.html valg/static/app.js valg/static/app.css
git commit -m "feat: resizable feed panel and columns with localStorage persistence"
```

---

## Task 9: Final check

- [ ] **Step 1: Run full test suite**

```bash
pytest tests/ -v
```

Expected: all pass, no reference to removed `/api/feed`.

- [ ] **Step 2: End-to-end smoke with demo**

```bash
python -m valg.server --demo
```

Open `http://localhost:5000`. Start the demo (Wave 1). Verify:
- Feed panel fills with place names as data arrives
- Clicking a place opens the Sted tab with party votes
- Delta shows `—` for first snapshot, numbers for subsequent ones
- After Wave 4/5 (fintælling), candidate votes appear in Sted tab
- Panel resize and column resize work and survive refresh
- "Vis ældre" button appears and loads older entries

- [ ] **Step 3: Commit any fixes, then final commit**

```bash
git add -p
git commit -m "fix: post-integration cleanup"
```
