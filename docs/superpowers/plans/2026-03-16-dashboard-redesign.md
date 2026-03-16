# Dashboard Redesign Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the text-output single-panel UI with a three-column interactive dashboard (parties | candidates | detail) with flip margins, candidate drilldown by polling district, and a persistent live feed strip.

**Architecture:** New JSON API routes in `server.py` backed by query functions in `queries.py`. Frontend is a single Alpine.js component served from `valg/templates/index.html` + `valg/static/`. The embedded `_HTML` string in `server.py` is replaced by Flask template rendering. Existing `/run`, `/csv/*`, `/sync-status` routes are untouched.

**Tech Stack:** Python/Flask, SQLite, Alpine.js 3.x (CDN), vanilla CSS (no build step)

**Spec:** `docs/superpowers/specs/2026-03-15-dashboard-redesign-design.md`

---

## Chunk 1: Backend — refactor + API routes

### Task 1: Move `get_seat_data` into `queries.py`

`queries.py` currently imports `_get_seat_data` from `cli.py` — a private function leaking across module boundaries. Move it to `queries.py` as a public function and update callers.

**Files:**
- Modify: `valg/queries.py` — add `get_seat_data` function, remove the `from valg.cli import _get_seat_data` import
- Modify: `valg/cli.py:41-74` — delete the `_get_seat_data` definition, add `from valg.queries import get_seat_data as _get_seat_data` near the top

- [ ] **Step 1: Write a failing test**

Add to `tests/test_queries.py`:

```python
def test_get_seat_data_importable_from_queries():
    from valg.queries import get_seat_data  # noqa: F401 — just checking it exists here
```

Run: `pytest tests/test_queries.py::test_get_seat_data_importable_from_queries -v`
Expected: FAIL with `ImportError: cannot import name 'get_seat_data' from 'valg.queries'`

- [ ] **Step 2: Move the function into `queries.py`**

In `valg/queries.py`, replace the import line at the top:
```python
# REMOVE this line:
from valg.cli import _get_seat_data
```

Add this function (taken verbatim from `cli.py:41-74`) after the `from valg import calculator` import:

```python
def get_seat_data(conn):
    """Return (national_votes, storkreds_votes, kredsmandater) for the calculator."""
    national = {
        r["party_id"]: r["v"]
        for r in conn.execute(
            "SELECT party_id, SUM(votes) as v FROM party_votes GROUP BY party_id"
        ).fetchall()
    }
    if not national:
        national = {
            r["party_id"]: r["v"]
            for r in conn.execute(
                "SELECT party_id, SUM(votes) as v FROM results "
                "WHERE candidate_id IS NULL GROUP BY party_id"
            ).fetchall()
        }

    sk_rows = conn.execute(
        "SELECT pv.party_id, ok.storkreds_id, SUM(pv.votes) as v "
        "FROM party_votes pv "
        "JOIN opstillingskredse ok ON ok.id = pv.opstillingskreds_id "
        "GROUP BY pv.party_id, ok.storkreds_id"
    ).fetchall()
    storkreds: dict = {}
    for r in sk_rows:
        storkreds.setdefault(r["storkreds_id"], {})[r["party_id"]] = r["v"]

    kredsmandater = {
        r["id"]: (r["n_kredsmandater"] or 0)
        for r in conn.execute("SELECT id, n_kredsmandater FROM storkredse").fetchall()
    }
    return national, storkreds, kredsmandater
```

Replace the three existing call sites in `queries.py` (in `query_status`, `query_flip`, `query_party`) from `_get_seat_data(conn)` to `get_seat_data(conn)`.

- [ ] **Step 3: Update `cli.py`**

In `valg/cli.py`, add at the top (after the existing imports, before `console = Console()`):
```python
from valg.queries import get_seat_data as _get_seat_data
```

Delete lines 41–74 (the entire `def _get_seat_data(conn):` function body).

- [ ] **Step 4: Run all tests**

```bash
pytest tests/test_queries.py tests/test_cli.py -v
```
Expected: All PASS (including the new test).

- [ ] **Step 5: Commit**

```bash
git add valg/queries.py valg/cli.py tests/test_queries.py
git commit -m "refactor: move get_seat_data from cli to queries"
```

---

### Task 2: `query_api_status` + `/api/status` route

**Files:**
- Modify: `valg/queries.py` — add `query_api_status`
- Modify: `valg/server.py` — add `/api/status` route
- Modify: `tests/test_server.py` — add API tests

- [ ] **Step 1: Write failing tests**

Add to `tests/test_server.py`:

```python
def test_api_status_returns_json(client):
    resp = client.get("/api/status")
    assert resp.status_code == 200
    data = resp.get_json()
    assert "districts_reported" in data
    assert "districts_total" in data
    assert "last_sync" in data
    assert "just_synced" in data


def test_api_status_districts_reported_is_int(client):
    resp = client.get("/api/status")
    data = resp.get_json()
    assert isinstance(data["districts_reported"], int)
    assert isinstance(data["districts_total"], int)
```

Run: `pytest tests/test_server.py::test_api_status_returns_json -v`
Expected: FAIL with 404

- [ ] **Step 2: Add `query_api_status` to `queries.py`**

```python
def query_api_status(conn) -> dict:
    districts_reported = conn.execute(
        "SELECT COUNT(DISTINCT opstillingskreds_id) FROM party_votes"
    ).fetchone()[0]
    districts_total = conn.execute(
        "SELECT COUNT(*) FROM opstillingskredse"
    ).fetchone()[0]
    return {
        "districts_reported": districts_reported,
        "districts_total": districts_total,
    }
```

- [ ] **Step 3: Add `/api/status` route in `server.py`**

Inside `create_app`, after the existing `/sync-status` route:

```python
@app.get("/api/status")
def api_status():
    global _just_synced
    with _sync_lock:
        just = _just_synced
        _just_synced = False
    from valg.queries import query_api_status
    meta = query_api_status(_get_conn())
    return jsonify({
        "last_sync": _last_sync,
        "just_synced": just,
        **meta,
    })
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/test_server.py -v
```
Expected: All PASS.

- [ ] **Step 5: Commit**

```bash
git add valg/queries.py valg/server.py tests/test_server.py
git commit -m "feat: add /api/status endpoint"
```

---

### Task 3: `query_api_parties` + `/api/parties` route

**Files:**
- Modify: `valg/queries.py` — add `query_api_parties`
- Modify: `valg/server.py` — add `/api/parties` route
- Modify: `tests/test_server.py` — add tests

- [ ] **Step 1: Write failing tests**

Add to `tests/test_server.py`:

```python
def test_api_parties_returns_list(client):
    resp = client.get("/api/parties")
    assert resp.status_code == 200
    data = resp.get_json()
    assert isinstance(data, list)


def test_api_parties_shape_when_data_present(client_with_data):
    resp = client_with_data.get("/api/parties")
    data = resp.get_json()
    assert len(data) > 0
    party = data[0]
    assert all(k in party for k in ["id", "letter", "name", "votes", "seats", "pct", "gain", "lose"])
    assert data == sorted(data, key=lambda p: -p["votes"])


def test_api_parties_empty_db_returns_empty_list(client):
    resp = client.get("/api/parties")
    assert resp.get_json() == []
```

You will need a `client_with_data` fixture. Add to `tests/test_server.py`:

```python
import pytest
from tests.synthetic.generator import generate_election, load_into_db
from valg.models import get_connection, init_db

@pytest.fixture
def client_with_data(tmp_path):
    db = tmp_path / "test.db"
    conn = get_connection(str(db))
    init_db(conn)
    e = generate_election(seed=42)
    load_into_db(conn, e, phase="preliminary")
    conn.close()
    from valg.server import create_app
    app = create_app(db_path=db, data_dir=tmp_path / "data")
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c
```

Run: `pytest tests/test_server.py::test_api_parties_returns_list -v`
Expected: FAIL with 404

- [ ] **Step 2: Add `query_api_parties` to `queries.py`**

```python
def query_api_parties(conn) -> list[dict]:
    national, storkreds, kredsmandater = get_seat_data(conn)
    if not national:
        return []

    seats = calculator.allocate_seats_total(national, storkreds, kredsmandater)
    total_votes = sum(national.values()) or 1

    party_rows = {
        r["id"]: {"id": r["id"], "letter": r["letter"], "name": r["name"]}
        for r in conn.execute("SELECT id, letter, name FROM parties").fetchall()
    }

    result = []
    for party_id, votes in sorted(national.items(), key=lambda x: -x[1]):
        info = party_rows.get(party_id, {"id": party_id, "letter": None, "name": party_id})
        seat_count = seats.get(party_id, 0)
        gain = calculator.votes_to_gain_seat(party_id, national, storkreds, kredsmandater)
        lose = calculator.votes_to_lose_seat(party_id, national, storkreds, kredsmandater)
        result.append({
            "id": party_id,
            "letter": info["letter"],
            "name": info["name"],
            "votes": votes,
            "seats": seat_count,
            "pct": round(votes / total_votes * 100, 1),
            "gain": gain,
            "lose": lose,
        })
    return result
```

- [ ] **Step 3: Add `/api/parties` route in `server.py`**

```python
@app.get("/api/parties")
def api_parties():
    from valg.queries import query_api_parties
    return jsonify(query_api_parties(_get_conn()))
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/test_server.py -v
```
Expected: All PASS.

- [ ] **Step 5: Commit**

```bash
git add valg/queries.py valg/server.py tests/test_server.py
git commit -m "feat: add /api/parties endpoint"
```

---

### Task 4: `query_api_candidates` + `/api/candidates` route

**Files:**
- Modify: `valg/queries.py` — add `query_api_candidates`
- Modify: `valg/server.py` — add `/api/candidates` route
- Modify: `tests/test_server.py` — add tests

- [ ] **Step 1: Write failing tests**

Add to `tests/test_server.py`:

```python
def test_api_candidates_returns_list(client):
    resp = client.get("/api/candidates?party_ids=")
    assert resp.status_code == 200
    assert resp.get_json() == []


def test_api_candidates_shape(client_with_data):
    # Get a valid party id first
    parties = client_with_data.get("/api/parties").get_json()
    assert len(parties) > 0
    party_id = parties[0]["id"]

    resp = client_with_data.get(f"/api/candidates?party_ids={party_id}")
    data = resp.get_json()
    assert len(data) > 0
    c = data[0]
    assert all(k in c for k in ["id", "name", "party_id", "party_letter", "opstillingskreds", "ballot_position"])
    assert all(r["party_id"] == party_id for r in data)


def test_api_candidates_grouped_by_party(client_with_data):
    parties = client_with_data.get("/api/parties").get_json()
    ids = ",".join(p["id"] for p in parties[:2])
    data = client_with_data.get(f"/api/candidates?party_ids={ids}").get_json()
    party_ids_seen = [r["party_id"] for r in data]
    # Rows should be grouped (all of party 1 before all of party 2)
    assert party_ids_seen == sorted(party_ids_seen)
```

Run: `pytest tests/test_server.py::test_api_candidates_returns_list -v`
Expected: FAIL with 404

- [ ] **Step 2: Add `query_api_candidates` to `queries.py`**

```python
def query_api_candidates(conn, party_ids: list[str]) -> list[dict]:
    if not party_ids:
        return []
    placeholders = ",".join("?" * len(party_ids))
    rows = conn.execute(
        f"SELECT c.id, c.name, c.party_id, p.letter as party_letter, "
        f"ok.name as opstillingskreds, c.ballot_position "
        f"FROM candidates c "
        f"JOIN parties p ON c.party_id = p.id "
        f"JOIN opstillingskredse ok ON c.opstillingskreds_id = ok.id "
        f"WHERE c.party_id IN ({placeholders}) "
        f"ORDER BY c.party_id, c.ballot_position",
        party_ids,
    ).fetchall()
    return [dict(r) for r in rows]
```

- [ ] **Step 3: Add `/api/candidates` route in `server.py`**

```python
@app.get("/api/candidates")
def api_candidates():
    raw = request.args.get("party_ids", "")
    party_ids = [p.strip() for p in raw.split(",") if p.strip()]
    from valg.queries import query_api_candidates
    return jsonify(query_api_candidates(_get_conn(), party_ids))
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/test_server.py -v
```
Expected: All PASS.

- [ ] **Step 5: Commit**

```bash
git add valg/queries.py valg/server.py tests/test_server.py
git commit -m "feat: add /api/candidates endpoint"
```

---

### Task 5: `query_api_party_detail` + `/api/party-detail` route

**Files:**
- Modify: `valg/queries.py` — add `query_api_party_detail`
- Modify: `valg/server.py` — add `/api/party-detail` route
- Modify: `tests/test_server.py` — add tests

- [ ] **Step 1: Write failing tests**

Add to `tests/test_server.py`:

```python
def test_api_party_detail_empty_ids_returns_empty(client):
    resp = client.get("/api/party-detail?party_ids=")
    assert resp.status_code == 200
    assert resp.get_json() == []


def test_api_party_detail_shape(client_with_data):
    parties = client_with_data.get("/api/parties").get_json()
    party_id = parties[0]["id"]
    resp = client_with_data.get(f"/api/party-detail?party_ids={party_id}")
    data = resp.get_json()
    assert len(data) == 1
    p = data[0]
    assert all(k in p for k in ["id", "letter", "name", "votes", "pct", "seats_total", "seats_by_storkreds"])
    assert isinstance(p["seats_by_storkreds"], list)
```

Run: `pytest tests/test_server.py::test_api_party_detail_empty_ids_returns_empty -v`
Expected: FAIL with 404

- [ ] **Step 2: Add `query_api_party_detail` to `queries.py`**

```python
def query_api_party_detail(conn, party_ids: list[str]) -> list[dict]:
    if not party_ids:
        return []

    national, storkreds_votes, kredsmandater = get_seat_data(conn)
    if not national:
        return []

    seats = calculator.allocate_seats_total(national, storkreds_votes, kredsmandater)
    total_votes = sum(national.values()) or 1

    storkreds_names = {
        r["id"]: r["name"]
        for r in conn.execute("SELECT id, name FROM storkredse").fetchall()
    }

    placeholders = ",".join("?" * len(party_ids))
    party_rows = {
        r["id"]: r
        for r in conn.execute(
            f"SELECT id, letter, name FROM parties WHERE id IN ({placeholders})",
            party_ids,
        ).fetchall()
    }

    result = []
    for party_id in party_ids:
        if party_id not in national:
            continue

        # Kredsmandater breakdown per storkreds (D'Hondt per storkreds)
        seats_breakdown = []
        for sk_id, sk_votes in storkreds_votes.items():
            n = kredsmandater.get(sk_id, 0)
            if n <= 0:
                continue
            sk_seats = calculator.dhondt(sk_votes, n)
            s = sk_seats.get(party_id, 0)
            if s > 0:
                seats_breakdown.append({
                    "name": storkreds_names.get(sk_id, sk_id),
                    "seats": s,
                })

        info = party_rows.get(party_id, {"id": party_id, "letter": None, "name": party_id})
        result.append({
            "id": party_id,
            "letter": info["letter"],
            "name": info["name"],
            "votes": national[party_id],
            "pct": round(national[party_id] / total_votes * 100, 1),
            "seats_total": seats.get(party_id, 0),
            "seats_by_storkreds": seats_breakdown,
        })
    return result
```

- [ ] **Step 3: Add `/api/party-detail` route in `server.py`**

```python
@app.get("/api/party-detail")
def api_party_detail():
    raw = request.args.get("party_ids", "")
    party_ids = [p.strip() for p in raw.split(",") if p.strip()]
    from valg.queries import query_api_party_detail
    return jsonify(query_api_party_detail(_get_conn(), party_ids))
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/test_server.py -v
```
Expected: All PASS.

- [ ] **Step 5: Commit**

```bash
git add valg/queries.py valg/server.py tests/test_server.py
git commit -m "feat: add /api/party-detail endpoint"
```

---

### Task 6: `query_api_candidate` + `/api/candidate/<id>` route

**Files:**
- Modify: `valg/queries.py` — add `query_api_candidate`
- Modify: `valg/server.py` — add `/api/candidate/<id>` route
- Modify: `tests/test_server.py` — add tests

- [ ] **Step 1: Write failing tests**

Add to `tests/test_server.py`:

```python
def test_api_candidate_unknown_returns_404(client):
    resp = client.get("/api/candidate/nonexistent")
    assert resp.status_code == 404


def test_api_candidate_before_fintaelling_returns_unavailable(client_with_data):
    # preliminary phase only — no candidate results
    parties = client_with_data.get("/api/parties").get_json()
    candidates = client_with_data.get(
        f"/api/candidates?party_ids={parties[0]['id']}"
    ).get_json()
    cid = candidates[0]["id"]
    resp = client_with_data.get(f"/api/candidate/{cid}")
    data = resp.get_json()
    assert data["available"] is False
    assert "name" in data
    assert "party_letter" in data
    assert "by_district" not in data


def test_api_candidate_after_fintaelling_returns_districts(client_with_final_data):
    parties = client_with_final_data.get("/api/parties").get_json()
    candidates = client_with_final_data.get(
        f"/api/candidates?party_ids={parties[0]['id']}"
    ).get_json()
    cid = candidates[0]["id"]
    resp = client_with_final_data.get(f"/api/candidate/{cid}")
    data = resp.get_json()
    assert data["available"] is True
    assert "total_votes" in data
    assert "by_district" in data
    assert "polling_districts_reported" in data
    assert "polling_districts_total" in data
    # votes=null means unreported, votes>=0 means reported
    for d in data["by_district"]:
        assert d["votes"] is None or isinstance(d["votes"], int)
```

Add a `client_with_final_data` fixture to `tests/test_server.py`:

```python
@pytest.fixture
def client_with_final_data(tmp_path):
    db = tmp_path / "test.db"
    conn = get_connection(str(db))
    init_db(conn)
    e = generate_election(seed=42)
    load_into_db(conn, e, phase="preliminary")
    load_into_db(conn, e, phase="final")
    conn.close()
    from valg.server import create_app
    app = create_app(db_path=db, data_dir=tmp_path / "data")
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c
```

Run: `pytest tests/test_server.py::test_api_candidate_unknown_returns_404 -v`
Expected: FAIL with 404

- [ ] **Step 2: Add `query_api_candidate` to `queries.py`**

```python
def query_api_candidate(conn, candidate_id: str) -> dict | None:
    row = conn.execute(
        "SELECT c.id, c.name, c.opstillingskreds_id, p.letter as party_letter "
        "FROM candidates c JOIN parties p ON c.party_id = p.id WHERE c.id = ?",
        (candidate_id,),
    ).fetchone()
    if not row:
        return None

    has_data = conn.execute(
        "SELECT 1 FROM results WHERE candidate_id = ? LIMIT 1", (candidate_id,)
    ).fetchone()
    if not has_data:
        return {"name": row["name"], "party_letter": row["party_letter"], "available": False}

    latest = conn.execute(
        "SELECT MAX(snapshot_at) FROM results WHERE candidate_id = ?", (candidate_id,)
    ).fetchone()[0]

    districts = conn.execute(
        """
        SELECT ao.name, r.votes
        FROM afstemningsomraader ao
        LEFT JOIN results r
            ON r.afstemningsomraade_id = ao.id
            AND r.candidate_id = ?
            AND r.snapshot_at = ?
        WHERE ao.opstillingskreds_id = ?
        ORDER BY COALESCE(r.votes, -1) DESC
        """,
        (candidate_id, latest, row["opstillingskreds_id"]),
    ).fetchall()

    by_district = [{"name": d["name"], "votes": d["votes"]} for d in districts]
    reported = sum(1 for d in by_district if d["votes"] is not None)
    total_votes = sum(d["votes"] for d in by_district if d["votes"] is not None)

    return {
        "name": row["name"],
        "party_letter": row["party_letter"],
        "available": True,
        "total_votes": total_votes,
        "polling_districts_reported": reported,
        "polling_districts_total": len(by_district),
        "by_district": by_district,
    }
```

- [ ] **Step 3: Add `/api/candidate/<id>` route in `server.py`**

```python
@app.get("/api/candidate/<candidate_id>")
def api_candidate(candidate_id):
    from valg.queries import query_api_candidate
    data = query_api_candidate(_get_conn(), candidate_id)
    if data is None:
        return jsonify({"error": "not found"}), 404
    return jsonify(data)
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/test_server.py -v
```
Expected: All PASS.

- [ ] **Step 5: Commit**

```bash
git add valg/queries.py valg/server.py tests/test_server.py
git commit -m "feat: add /api/candidate/<id> endpoint"
```

---

### Task 7: `query_api_feed` + `/api/feed` route

**Files:**
- Modify: `valg/queries.py` — add `query_api_feed`
- Modify: `valg/server.py` — add `/api/feed` route
- Modify: `tests/test_server.py` — add tests

- [ ] **Step 1: Write failing tests**

Add to `tests/test_server.py`:

```python
def test_api_feed_returns_list(client):
    resp = client.get("/api/feed")
    assert resp.status_code == 200
    assert isinstance(resp.get_json(), list)


def test_api_feed_shape_when_events_exist(client_with_data):
    # Insert a test event directly
    from valg.models import get_connection
    # We can't easily test shape without events — just check the structure is a list
    resp = client_with_data.get("/api/feed")
    data = resp.get_json()
    assert isinstance(data, list)
    # Each item should have occurred_at and description if list is non-empty
    for item in data:
        assert "occurred_at" in item
        assert "description" in item


def test_api_feed_respects_limit(client):
    resp = client.get("/api/feed?limit=5")
    assert resp.status_code == 200
```

Run: `pytest tests/test_server.py::test_api_feed_returns_list -v`
Expected: FAIL with 404

- [ ] **Step 2: Add `query_api_feed` to `queries.py`**

```python
def query_api_feed(conn, limit: int = 50) -> list[dict]:
    rows = conn.execute(
        "SELECT occurred_at, description FROM events ORDER BY occurred_at DESC LIMIT ?",
        (limit,),
    ).fetchall()
    return [{"occurred_at": r["occurred_at"], "description": r["description"]} for r in rows]
```

- [ ] **Step 3: Add `/api/feed` route in `server.py`**

```python
@app.get("/api/feed")
def api_feed():
    limit = min(int(request.args.get("limit", 50)), 200)
    from valg.queries import query_api_feed
    return jsonify(query_api_feed(_get_conn(), limit))
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/test_server.py -v
```
Expected: All PASS.

- [ ] **Step 5: Commit**

```bash
git add valg/queries.py valg/server.py tests/test_server.py
git commit -m "feat: add /api/feed endpoint"
```

---

### Task 8: `query_api_candidate_feed` + `/api/candidate-feed/<id>` route

**Files:**
- Modify: `valg/queries.py` — add `query_api_candidate_feed`
- Modify: `valg/server.py` — add `/api/candidate-feed/<id>` route
- Modify: `tests/test_server.py` — add tests

- [ ] **Step 1: Write failing tests**

Add to `tests/test_server.py`:

```python
def test_api_candidate_feed_returns_list(client):
    resp = client.get("/api/candidate-feed/nonexistent")
    assert resp.status_code == 200
    assert resp.get_json() == []


def test_api_candidate_feed_shape_after_multiple_snapshots(tmp_path):
    """Feed requires >=2 snapshots to produce deltas."""
    from valg.models import get_connection, init_db
    from tests.synthetic.generator import generate_election, load_into_db

    db = tmp_path / "test.db"
    conn = get_connection(str(db))
    init_db(conn)
    e = generate_election(seed=42)
    load_into_db(conn, e, phase="preliminary")
    load_into_db(conn, e, phase="final")  # snapshot 2

    # Load a second final snapshot with different snapshot_at to get deltas
    import random
    rng = random.Random(99)
    snapshot2 = "2024-11-06T12:00:00"
    for ao in e["afstemningsomraader"]:
        for party in e["parties"]:
            for c in [c for c in e["candidates"]
                      if c["opstillingskreds_id"] == ao["opstillingskreds_id"]
                      and c["party_id"] == party["id"]]:
                votes = rng.randint(10, 600)
                conn.execute(
                    "INSERT OR IGNORE INTO results "
                    "(afstemningsomraade_id, party_id, candidate_id, votes, count_type, snapshot_at) "
                    "VALUES (?,?,?,?,?,?)",
                    (ao["id"], party["id"], c["id"], votes, "final", snapshot2),
                )
    conn.commit()

    candidate_id = e["candidates"][0]["id"]

    from valg.server import create_app
    app = create_app(db_path=db, data_dir=tmp_path / "data")
    app.config["TESTING"] = True
    with app.test_client() as client:
        resp = client.get(f"/api/candidate-feed/{candidate_id}")
        data = resp.get_json()
        assert isinstance(data, list)
        for item in data:
            assert "occurred_at" in item
            assert "district" in item
            assert "delta" in item
            assert item["delta"] > 0
```

Run: `pytest tests/test_server.py::test_api_candidate_feed_returns_list -v`
Expected: FAIL with 404

- [ ] **Step 2: Add `query_api_candidate_feed` to `queries.py`**

```python
def query_api_candidate_feed(conn, candidate_id: str, limit: int = 20) -> list[dict]:
    rows = conn.execute(
        """
        WITH ordered AS (
            SELECT r.afstemningsomraade_id,
                   r.votes,
                   r.snapshot_at,
                   ao.name AS district_name
            FROM results r
            JOIN afstemningsomraader ao ON ao.id = r.afstemningsomraade_id
            WHERE r.candidate_id = ?
        ),
        deltas AS (
            SELECT district_name,
                   snapshot_at,
                   votes - LAG(votes, 1, 0) OVER (
                       PARTITION BY afstemningsomraade_id ORDER BY snapshot_at
                   ) AS delta
            FROM ordered
        )
        SELECT district_name, snapshot_at AS occurred_at, delta
        FROM deltas
        WHERE delta > 0
        ORDER BY occurred_at DESC
        LIMIT ?
        """,
        (candidate_id, limit),
    ).fetchall()
    return [
        {"occurred_at": r["occurred_at"], "district": r["district_name"], "delta": r["delta"]}
        for r in rows
    ]
```

- [ ] **Step 3: Add `/api/candidate-feed/<id>` route in `server.py`**

```python
@app.get("/api/candidate-feed/<candidate_id>")
def api_candidate_feed(candidate_id):
    limit = min(int(request.args.get("limit", 20)), 100)
    from valg.queries import query_api_candidate_feed
    return jsonify(query_api_candidate_feed(_get_conn(), candidate_id, limit))
```

- [ ] **Step 4: Run all backend tests**

```bash
pytest tests/test_server.py tests/test_queries.py tests/test_cli.py -v
```
Expected: All PASS.

- [ ] **Step 5: Commit**

```bash
git add valg/queries.py valg/server.py tests/test_server.py
git commit -m "feat: add /api/candidate-feed/<id> endpoint"
```

---

## Chunk 2: Frontend — templates, CSS, Alpine.js

### Task 9: Switch `server.py` to Flask template rendering

Replace the embedded `_HTML` string with a proper Flask template. Flask automatically finds `valg/templates/` and `valg/static/` when the app is created with `Flask(__name__)` in `valg/server.py`.

**Files:**
- Create: `valg/templates/` directory (empty, just needs to exist)
- Create: `valg/static/` directory (empty, just needs to exist)
- Modify: `valg/server.py` — import `render_template`, update `/` route, remove `_HTML`

- [ ] **Step 1: Write failing test**

Add to `tests/test_server.py`:

```python
def test_index_serves_alpine_app(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert b"x-data" in resp.data  # Alpine.js component marker
    assert b"alpine" in resp.data.lower()
```

Run: `pytest tests/test_server.py::test_index_serves_alpine_app -v`
Expected: FAIL (current page doesn't have Alpine.js)

- [ ] **Step 2: Create directories**

Run from the project root (`valg/`):
```bash
mkdir -p valg/templates
mkdir -p valg/static
```

- [ ] **Step 3: Update `server.py` and fix the breaking test**

Add `render_template` to the Flask import line:
```python
from flask import Flask, Response, jsonify, render_template, request
```

Replace the `_HTML` block (lines 37–140) entirely — delete the whole `_HTML = """..."""` string.

Replace the `/` route:
```python
@app.get("/")
def index():
    return render_template("index.html")
```

Also update `test_index_returns_html` in `tests/test_server.py` — the `<pre>` tag no longer exists:
```python
def test_index_returns_html(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert b"valg" in resp.data
```

- [ ] **Step 4: Create a minimal placeholder `valg/templates/index.html`**

```html
<!DOCTYPE html>
<html lang="da">
<head><meta charset="utf-8"><title>valg</title></head>
<body x-data="dashboard()" x-init="init()">
  <p>Loading…</p>
  <script src="//cdn.jsdelivr.net/npm/alpinejs@3.x.x/dist/cdn.min.js" defer></script>
</body>
</html>
```

- [ ] **Step 5: Run test**

```bash
pytest tests/test_server.py::test_index_serves_alpine_app -v
```
Expected: PASS.

Also run existing server tests to confirm no regressions:
```bash
pytest tests/test_server.py -v
```

- [ ] **Step 6: Commit**

```bash
git add valg/server.py valg/templates/index.html valg/static/.gitkeep
git commit -m "feat: switch server to Flask template rendering"
```

---

### Task 10: Write `valg/static/app.css`

**Files:**
- Create: `valg/static/app.css`

No TDD for CSS — verify visually.

- [ ] **Step 1: Write `valg/static/app.css`**

```css
*, *::before, *::after { box-sizing: border-box; }

body {
  margin: 0;
  font-family: monospace;
  font-size: 13px;
  background: #0d1117;
  color: #c9d1d9;
  display: flex;
  flex-direction: column;
  height: 100vh;
  overflow: hidden;
}

/* ── Header ─────────────────────────────────────────────────────── */
.header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 16px;
  background: #161b22;
  border-bottom: 1px solid #30363d;
  flex-shrink: 0;
}
.header h1 { margin: 0; font-size: 1.1em; color: #58a6ff; }
.header .meta { font-size: 0.85em; color: #8b949e; }
.header .meta.pulsing { animation: pulse 1s ease-in-out infinite; }
@keyframes pulse { 0%,100% { opacity:1; } 50% { opacity:0.4; } }

/* ── Three columns ───────────────────────────────────────────────── */
.columns {
  display: flex;
  flex: 1;
  overflow: hidden;
}

.col {
  display: flex;
  flex-direction: column;
  border-right: 1px solid #30363d;
  overflow: hidden;
}
.col:last-child { border-right: none; flex: 1; }
.col-parties  { width: 220px; flex-shrink: 0; }
.col-candidates { width: 220px; flex-shrink: 0; }
.col-detail { flex: 1; }

.col-header {
  padding: 6px 12px;
  border-bottom: 1px solid #21262d;
  color: #8b949e;
  font-size: 0.8em;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  flex-shrink: 0;
}

.col-body {
  overflow-y: auto;
  flex: 1;
  padding: 4px 0;
}

/* ── Party rows ──────────────────────────────────────────────────── */
.party-row {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  padding: 6px 12px;
  cursor: pointer;
  user-select: none;
}
.party-row:hover { background: #161b22; }
.party-row.selected {
  background: #1c2128;
  border-left: 2px solid #3fb950;
}
.party-row.selected .party-name { color: #e6edf3; font-weight: bold; }
.party-row input[type=checkbox] { margin-top: 2px; flex-shrink: 0; accent-color: #3fb950; }
.party-name { color: #e6edf3; }
.party-sub  { color: #8b949e; font-size: 0.85em; margin-top: 1px; }
.flip-gain  { color: #3fb950; }
.flip-lose  { color: #f85149; }

/* ── Candidate rows ──────────────────────────────────────────────── */
.party-group-label {
  padding: 4px 12px 2px;
  color: #8b949e;
  font-size: 0.8em;
  text-transform: uppercase;
  margin-top: 6px;
}
.candidate-row {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  padding: 5px 12px;
  cursor: pointer;
  user-select: none;
}
.candidate-row:hover { background: #161b22; }
.candidate-row.focused {
  background: #1c2128;
  border-left: 2px solid #388bfd;
}
.candidate-row input[type=checkbox] { margin-top: 2px; flex-shrink: 0; accent-color: #388bfd; }
.cand-name { color: #e6edf3; }
.cand-sub  { color: #8b949e; font-size: 0.85em; margin-top: 1px; }

/* ── Right panel ─────────────────────────────────────────────────── */
.detail-body {
  padding: 12px 16px;
  overflow-y: auto;
  flex: 1;
}
.detail-placeholder {
  color: #8b949e;
  padding: 24px 16px;
}
.detail-section-label {
  color: #8b949e;
  font-size: 0.8em;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  margin: 12px 0 4px;
  border-top: 1px solid #21262d;
  padding-top: 8px;
}
.detail-section-label:first-child { border-top: none; margin-top: 0; padding-top: 0; }

/* ── Tables ──────────────────────────────────────────────────────── */
.data-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 0.95em;
}
.data-table th {
  color: #8b949e;
  text-align: left;
  padding: 3px 6px;
  border-bottom: 1px solid #21262d;
  font-weight: normal;
}
.data-table th:last-child { text-align: right; }
.data-table td {
  padding: 4px 6px;
  border-bottom: 1px solid #161b22;
  color: #e6edf3;
}
.data-table td:last-child { text-align: right; color: #3fb950; }
.data-table td.null-votes { color: #8b949e; text-align: right; }

/* ── Candidate feed items ────────────────────────────────────────── */
.feed-item-cand { color: #3fb950; font-size: 0.9em; margin: 2px 0; }

/* ── Party detail ────────────────────────────────────────────────── */
.party-detail-block { margin-bottom: 16px; }
.party-detail-name  { color: #e6edf3; font-weight: bold; margin-bottom: 4px; }
.party-detail-meta  { color: #8b949e; font-size: 0.9em; margin-bottom: 6px; }

/* ── Feed strip ──────────────────────────────────────────────────── */
.feed-strip {
  display: flex;
  align-items: center;
  gap: 0;
  padding: 5px 12px;
  border-top: 1px solid #30363d;
  background: #0d1117;
  overflow-x: auto;
  white-space: nowrap;
  flex-shrink: 0;
  scrollbar-width: thin;
}
.feed-strip-label {
  color: #8b949e;
  font-size: 0.8em;
  text-transform: uppercase;
  margin-right: 16px;
  flex-shrink: 0;
}
.feed-strip-item {
  color: #58a6ff;
  font-size: 0.85em;
  margin-right: 24px;
  flex-shrink: 0;
}
.feed-strip-empty { color: #8b949e; font-size: 0.85em; }

/* ── Scrollbar ───────────────────────────────────────────────────── */
::-webkit-scrollbar { width: 4px; height: 4px; }
::-webkit-scrollbar-track { background: transparent; }
::-webkit-scrollbar-thumb { background: #30363d; border-radius: 2px; }
```

- [ ] **Step 2: Commit**

```bash
git add valg/static/app.css
git commit -m "feat: add dashboard CSS"
```

---

### Task 11: Write `valg/templates/index.html` and `valg/static/app.js`

**Files:**
- Create: `valg/static/app.js` — full Alpine.js component
- Modify: `valg/templates/index.html` — full dashboard HTML

- [ ] **Step 1: Write `valg/static/app.js`**

```javascript
document.addEventListener('alpine:init', () => {
  Alpine.data('dashboard', () => ({
    selectedPartyIds: [],
    selectedCandidateIds: [],
    focusedCandidateId: null,

    parties: [],
    candidates: [],
    partyDetail: null,
    candidateDetail: null,
    candidateFeed: [],
    feed: [],

    lastSynced: null,
    districtsReported: null,
    districtsTotal: null,
    syncing: false,  // true during just_synced refresh — drives pulsing header

    async init() {
      await this._fetchAll()
      setInterval(() => this._poll(), 10000)
    },

    async _fetchAll() {
      await Promise.all([this._fetchStatus(), this._fetchParties(), this._fetchFeed()])
      if (this.selectedPartyIds.length) {
        await Promise.all([this._fetchCandidates(), this._fetchPartyDetail()])
      }
      if (this.focusedCandidateId) {
        await Promise.all([this._fetchCandidateDetail(), this._fetchCandidateFeed()])
      }
    },

    async _poll() {
      const resp = await fetch('/api/status').catch(() => null)
      if (!resp) return
      const data = await resp.json()
      this.lastSynced = data.last_sync
      this.districtsReported = data.districts_reported
      this.districtsTotal = data.districts_total
      if (data.just_synced) {
        this.syncing = true
        await this._fetchAll()
        this.syncing = false
        return
      }
      await Promise.all([this._fetchParties(), this._fetchFeed()])
      if (this.selectedPartyIds.length) {
        await Promise.all([this._fetchCandidates(), this._fetchPartyDetail()])
      }
      if (this.focusedCandidateId) {
        await Promise.all([this._fetchCandidateDetail(), this._fetchCandidateFeed()])
      }
    },

    async _fetchStatus() {
      const resp = await fetch('/api/status').catch(() => null)
      if (!resp) return
      const data = await resp.json()
      this.lastSynced = data.last_sync
      this.districtsReported = data.districts_reported
      this.districtsTotal = data.districts_total
    },

    async _fetchParties() {
      const resp = await fetch('/api/parties').catch(() => null)
      if (!resp) return
      this.parties = await resp.json()
    },

    async _fetchFeed() {
      const resp = await fetch('/api/feed?limit=50').catch(() => null)
      if (!resp) return
      this.feed = await resp.json()
    },

    async _fetchCandidates() {
      if (!this.selectedPartyIds.length) { this.candidates = []; return }
      const params = new URLSearchParams({ party_ids: this.selectedPartyIds.join(',') })
      const resp = await fetch('/api/candidates?' + params).catch(() => null)
      if (!resp) return
      this.candidates = await resp.json()
    },

    async _fetchPartyDetail() {
      if (!this.selectedPartyIds.length) { this.partyDetail = null; return }
      const params = new URLSearchParams({ party_ids: this.selectedPartyIds.join(',') })
      const resp = await fetch('/api/party-detail?' + params).catch(() => null)
      if (!resp) return
      this.partyDetail = await resp.json()
    },

    async _fetchCandidateDetail() {
      if (!this.focusedCandidateId) return
      const resp = await fetch('/api/candidate/' + this.focusedCandidateId).catch(() => null)
      if (!resp) return
      this.candidateDetail = await resp.json()
    },

    async _fetchCandidateFeed() {
      if (!this.focusedCandidateId) return
      const resp = await fetch('/api/candidate-feed/' + this.focusedCandidateId + '?limit=20').catch(() => null)
      if (!resp) return
      this.candidateFeed = await resp.json()
    },

    toggleParty(partyId) {
      if (this.selectedPartyIds.includes(partyId)) {
        this.selectedPartyIds = this.selectedPartyIds.filter(id => id !== partyId)
        // Clear focused candidate if their party was deselected
        if (this.focusedCandidateId) {
          const fc = this.candidates.find(c => c.id === this.focusedCandidateId)
          if (fc && fc.party_id === partyId) {
            this.focusedCandidateId = null
            this.candidateDetail = null
            this.candidateFeed = []
          }
        }
      } else {
        this.selectedPartyIds = [...this.selectedPartyIds, partyId]
      }
      Promise.all([this._fetchCandidates(), this._fetchPartyDetail()])
    },

    toggleCandidateCheck(candidateId) {
      if (this.selectedCandidateIds.includes(candidateId)) {
        this.selectedCandidateIds = this.selectedCandidateIds.filter(id => id !== candidateId)
      } else {
        this.selectedCandidateIds = [...this.selectedCandidateIds, candidateId]
      }
    },

    focusCandidate(candidateId) {
      if (this.focusedCandidateId === candidateId) {
        this.focusedCandidateId = null
        this.candidateDetail = null
        this.candidateFeed = []
      } else {
        this.focusedCandidateId = candidateId
        Promise.all([this._fetchCandidateDetail(), this._fetchCandidateFeed()])
      }
    },

    get candidatesByParty() {
      const groups = {}
      for (const c of this.candidates) {
        if (!groups[c.party_id]) {
          groups[c.party_id] = { party_id: c.party_id, letter: c.party_letter, candidates: [] }
        }
        groups[c.party_id].candidates.push(c)
      }
      return Object.values(groups)
    },

    get selectedPartyLetters() {
      return this.parties
        .filter(p => this.selectedPartyIds.includes(p.id))
        .map(p => p.letter || p.id)
        .join(', ')
    },

    formatNum(n) {
      if (n == null) return '—'
      return n.toLocaleString('da-DK')
    },

    formatTime(isoStr) {
      if (!isoStr) return ''
      return isoStr.slice(11, 16)
    },
  }))
})
```

- [ ] **Step 2: Write `valg/templates/index.html`**

```html
<!DOCTYPE html>
<html lang="da">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>valg</title>
  <link rel="stylesheet" href="/static/app.css">
  <script src="//cdn.jsdelivr.net/npm/alpinejs@3.x.x/dist/cdn.min.js" defer></script>
  <script src="/static/app.js"></script>
</head>
<body x-data="dashboard()" x-init="init()">

  <!-- Header -->
  <header class="header">
    <h1>valg</h1>
    <span class="meta" :class="{'pulsing': syncing}">
      <span x-text="lastSynced ? 'Synced ' + lastSynced : 'Waiting for sync…'"></span>
      <span x-show="districtsTotal > 0">
        &bull;
        <span x-text="(districtsReported || 0) + '/' + (districtsTotal || 0) + ' districts'"></span>
      </span>
    </span>
  </header>

  <!-- Three columns -->
  <div class="columns">

    <!-- Parties -->
    <div class="col col-parties">
      <div class="col-header">Parties</div>
      <div class="col-body">
        <template x-if="parties.length === 0">
          <div class="detail-placeholder">Waiting for data…</div>
        </template>
        <template x-for="p in parties" :key="p.id">
          <div class="party-row" :class="{selected: selectedPartyIds.includes(p.id)}"
               @click="toggleParty(p.id)">
            <input type="checkbox" :checked="selectedPartyIds.includes(p.id)"
                   @click.stop="toggleParty(p.id)">
            <div>
              <div class="party-name" x-text="(p.letter || p.id) + ' — ' + p.name"></div>
              <div class="party-sub">
                <span x-text="formatNum(p.votes) + ' votes · ' + p.seats + ' seats'"></span>
              </div>
              <div class="party-sub">
                <span class="flip-gain" x-text="'+' + formatNum(p.gain) + ' to gain'"></span>
                <span style="color:#8b949e"> · </span>
                <span class="flip-lose" x-text="'−' + formatNum(p.lose) + ' to lose'"></span>
              </div>
            </div>
          </div>
        </template>
      </div>
    </div>

    <!-- Candidates -->
    <div class="col col-candidates">
      <div class="col-header">
        <span x-show="selectedPartyIds.length === 0">Candidates</span>
        <span x-show="selectedPartyIds.length > 0"
              x-text="'Candidates — ' + selectedPartyLetters"></span>
      </div>
      <div class="col-body">
        <template x-if="selectedPartyIds.length === 0">
          <div class="detail-placeholder" style="padding:16px 12px;color:#8b949e">
            Select a party
          </div>
        </template>
        <template x-for="group in candidatesByParty" :key="group.party_id">
          <div>
            <div class="party-group-label" x-text="group.letter"></div>
            <template x-for="c in group.candidates" :key="c.id">
              <div class="candidate-row"
                   :class="{focused: focusedCandidateId === c.id}"
                   @click="focusCandidate(c.id)">
                <input type="checkbox" :checked="selectedCandidateIds.includes(c.id)"
                       @click.stop="toggleCandidateCheck(c.id)">
                <div>
                  <div class="cand-name" x-text="c.name"></div>
                  <div class="cand-sub"
                       x-text="c.opstillingskreds + ' · #' + c.ballot_position"></div>
                </div>
              </div>
            </template>
          </div>
        </template>
      </div>
    </div>

    <!-- Right panel -->
    <div class="col col-detail">
      <div class="col-header">
        <span x-show="!focusedCandidateId">Details</span>
        <span x-show="focusedCandidateId && candidateDetail"
              x-text="candidateDetail ? candidateDetail.name + ' (' + candidateDetail.party_letter + ')' : ''">
        </span>
      </div>
      <div class="detail-body">

        <!-- Party detail mode -->
        <template x-if="!focusedCandidateId">
          <div>
            <template x-if="!selectedPartyIds.length">
              <div class="detail-placeholder">Select a party to see details</div>
            </template>
            <template x-if="selectedPartyIds.length && !partyDetail">
              <div class="detail-placeholder">Loading…</div>
            </template>
            <template x-if="partyDetail">
              <div>
                <template x-for="p in partyDetail" :key="p.id">
                  <div class="party-detail-block">
                    <div class="party-detail-name"
                         x-text="(p.letter || p.id) + ' — ' + p.name"></div>
                    <div class="party-detail-meta"
                         x-text="formatNum(p.votes) + ' votes (' + p.pct + '%) · ' + p.seats_total + ' seats'">
                    </div>
                    <template x-if="p.seats_by_storkreds.length > 0">
                      <table class="data-table">
                        <thead>
                          <tr><th>Storkreds</th><th>Kredsmandater</th></tr>
                        </thead>
                        <tbody>
                          <template x-for="sk in p.seats_by_storkreds" :key="sk.name">
                            <tr>
                              <td x-text="sk.name"></td>
                              <td x-text="sk.seats"></td>
                            </tr>
                          </template>
                        </tbody>
                      </table>
                    </template>
                  </div>
                </template>
              </div>
            </template>
          </div>
        </template>

        <!-- Candidate detail mode -->
        <template x-if="focusedCandidateId">
          <div>
            <template x-if="!candidateDetail">
              <div class="detail-placeholder">Loading…</div>
            </template>
            <template x-if="candidateDetail && !candidateDetail.available">
              <div class="detail-placeholder">
                Candidate votes available after fintælling begins
              </div>
            </template>
            <template x-if="candidateDetail && candidateDetail.available">
              <div>
                <div class="party-detail-meta"
                     x-text="formatNum(candidateDetail.total_votes) + ' votes total · '
                            + candidateDetail.polling_districts_reported + '/'
                            + candidateDetail.polling_districts_total + ' districts'">
                </div>
                <table class="data-table">
                  <thead>
                    <tr><th>District</th><th>Votes</th></tr>
                  </thead>
                  <tbody>
                    <template x-for="d in candidateDetail.by_district" :key="d.name">
                      <tr>
                        <td x-text="d.name"></td>
                        <td :class="{'null-votes': d.votes === null}"
                            x-text="d.votes !== null ? formatNum(d.votes) : '—'"></td>
                      </tr>
                    </template>
                  </tbody>
                </table>
                <div class="detail-section-label">Candidate feed</div>
                <template x-if="candidateFeed.length === 0">
                  <div style="color:#8b949e;font-size:0.9em">No updates yet</div>
                </template>
                <template x-for="item in candidateFeed" :key="item.occurred_at + item.district">
                  <div class="feed-item-cand"
                       x-text="'+' + formatNum(item.delta) + ' · ' + item.district
                              + ' · ' + formatTime(item.occurred_at)">
                  </div>
                </template>
              </div>
            </template>
          </div>
        </template>

      </div>
    </div>

  </div>

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

</body>
</html>
```

- [ ] **Step 3: Run full test suite**

```bash
pytest tests/ -v --ignore=tests/e2e
```
Expected: All PASS. The `test_index_returns_html` test checks for `b"valg"` and `b"<pre"` — `<pre` is no longer present. Update that test:

```python
def test_index_returns_html(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert b"valg" in resp.data
    assert b"alpine" in resp.data.lower()  # replaces <pre check
```

- [ ] **Step 4: Smoke test in browser**

Start the server:
```bash
python -m valg.server
```
Open http://localhost:5000. Verify:
- Three-column layout renders
- Party column shows "Waiting for data…" on empty DB
- No JS errors in browser console

Optionally load fake data first:
```bash
python -m valg --db /tmp/test.db sync --fake --wave 0
python -m valg --db /tmp/test.db sync --fake --wave 1
python -m valg.server  # (with VALG_DB env var or tmp path)
```

- [ ] **Step 5: Commit**

```bash
git add valg/templates/index.html valg/static/app.js valg/static/app.css tests/test_server.py
git commit -m "feat: dashboard redesign — three-column Alpine.js UI"
```

---

## Final verification

- [ ] Run the full test suite:

```bash
pytest tests/ -v --ignore=tests/e2e
```
Expected: All PASS.

- [ ] Check no regressions in existing routes:

```bash
pytest tests/test_server.py tests/test_queries.py tests/test_cli.py -v
```
