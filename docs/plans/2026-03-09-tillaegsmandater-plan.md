# Tillægsmandater Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace the approximate national Sainte-Laguë subtraction with proper Sainte-Laguë from kredsmandat baseline, assign tillæg seats to storkredse via D'Hondt, track seat changes in differ.py, and expose the breakdown in the CLI.

**Architecture:** Four new/updated pure functions in `calculator.py` (`saint_lague_from_baseline`, `dhondt_from_baseline`, `allocate_kredsmandater_detail`, `allocate_tillaeg_to_storkredse`, `allocate_seats_detail`). `allocate_seats_total` is refactored to delegate to `allocate_seats_detail`. `differ.py` gets `diff_seat_projections`. CLI `party` and `status` commands get a storkreds breakdown column.

**Tech Stack:** Python 3.11, SQLite (existing schema — all needed data already in DB), pytest, Rich tables.

---

## Background: How Proper Tillægsmandater Work

**Kredsmandater (135):** D'Hondt per storkreds. Already correct.

**Tillægsmandater (40):** National Sainte-Laguë, but each party's divisor sequence starts at `2k+1` where `k` = kredsmandater already won by that party nationally. A party with 10 kredsmandater starts its Sainte-Laguë sequence at divisor 21 (not 1.4).

**Storkreds assignment of tillæg:** Once we know party A gets 5 national tillæg seats, D'Hondt within party A across its storkredse determines *which* storkreds receives each seat. Divisor for each storkreds starts at `kreds_already_won_in_that_storkreds + 1`.

---

## Task 1: `dhondt_from_baseline` in calculator.py

A generalised D'Hondt that starts each entity's divisor at `baseline[entity] + 1`.
Used for storkreds assignment of tillæg seats.

**Files:**
- Modify: `valg/calculator.py`
- Test: `tests/test_calculator.py`

**Step 1: Write the failing test**

```python
# tests/test_calculator.py — append after existing tests
from valg.calculator import dhondt_from_baseline

def test_dhondt_from_baseline_zero_baseline_matches_dhondt():
    # With no baseline seats, should match regular D'Hondt
    assert dhondt_from_baseline({"A": 3000, "B": 1000}, {}, 4) == dhondt({"A": 3000, "B": 1000}, 4)

def test_dhondt_from_baseline_shifts_divisors():
    # A has 2 baseline seats (divisor starts at 3), B has 0 (divisor starts at 1)
    # B should get more seats than it would without the baseline
    result = dhondt_from_baseline({"A": 1000, "B": 1000}, {"A": 2}, 2)
    assert result["B"] >= result["A"]

def test_dhondt_from_baseline_total_equals_n():
    result = dhondt_from_baseline({"A": 3000, "B": 2000, "C": 1000}, {"A": 5, "B": 2}, 4)
    assert sum(result.values()) == 4
```

**Step 2: Run to verify failure**

```bash
pytest tests/test_calculator.py::test_dhondt_from_baseline_zero_baseline_matches_dhondt -v
```
Expected: `FAILED` — `ImportError: cannot import name 'dhondt_from_baseline'`

**Step 3: Implement**

Add to `valg/calculator.py` after `dhondt`:

```python
def dhondt_from_baseline(
    entity_votes: dict[str, int],
    baseline: dict[str, int],
    n_seats: int,
) -> dict[str, int]:
    """
    D'Hondt where each entity's divisor starts at baseline[entity] + 1.
    Returns {entity: additional_seats_allocated} (baseline not included).
    """
    seats = {e: 0 for e in entity_votes}
    if n_seats <= 0:
        return seats

    heap = []
    for entity, votes in entity_votes.items():
        if votes > 0:
            k = baseline.get(entity, 0)
            heapq.heappush(heap, (-votes / (k + 1), entity))

    for _ in range(n_seats):
        if not heap:
            break
        _, entity = heapq.heappop(heap)
        seats[entity] += 1
        k = baseline.get(entity, 0) + seats[entity]
        heapq.heappush(heap, (-entity_votes[entity] / (k + 1), entity))

    return seats
```

Also add `dhondt_from_baseline` to the import in `tests/test_calculator.py`.

**Step 4: Run tests**

```bash
pytest tests/test_calculator.py -k "baseline" -v
```
Expected: all 3 pass.

**Step 5: Commit**

```bash
git add valg/calculator.py tests/test_calculator.py
git commit -m "feat: add dhondt_from_baseline for storkreds tillæg assignment"
```

---

## Task 2: `saint_lague_from_baseline` in calculator.py

Sainte-Laguë where each party's divisor sequence starts at `2k+1` where `k` = baseline (kredsmandater won). This allocates the 40 national tillæg seats.

**Files:**
- Modify: `valg/calculator.py`
- Test: `tests/test_calculator.py`

**Step 1: Write the failing test**

```python
from valg.calculator import saint_lague_from_baseline

def test_saint_lague_from_baseline_zero_baseline():
    # With no baseline, first divisor is 1 — same as standard Saint-Laguë
    result = saint_lague_from_baseline({"A": 1000, "B": 1000}, {}, 4)
    assert sum(result.values()) == 4

def test_saint_lague_from_baseline_total_equals_n():
    result = saint_lague_from_baseline(
        {"A": 50000, "B": 30000, "C": 20000},
        {"A": 10, "B": 5, "C": 3},
        40,
    )
    assert sum(result.values()) == 40

def test_saint_lague_from_baseline_high_baseline_penalises_party():
    # Party A already has 50 kreds seats (divisor starts at 101)
    # Party B has 0 (divisor starts at 1)
    # B should get far more tillaeg seats
    result = saint_lague_from_baseline(
        {"A": 100000, "B": 50000},
        {"A": 50, "B": 0},
        10,
    )
    assert result["B"] > result["A"]

def test_saint_lague_from_baseline_returns_all_parties():
    result = saint_lague_from_baseline({"A": 1000, "B": 500}, {}, 3)
    assert set(result.keys()) == {"A", "B"}
```

**Step 2: Run to verify failure**

```bash
pytest tests/test_calculator.py::test_saint_lague_from_baseline_zero_baseline -v
```
Expected: `FAILED` — `ImportError`

**Step 3: Implement**

Add to `valg/calculator.py` after `modified_saint_lague`:

```python
def saint_lague_from_baseline(
    qualifying_votes: dict[str, int],
    baseline: dict[str, int],
    n_tillaeg: int,
) -> dict[str, int]:
    """
    Allocate n_tillaeg seats using Sainte-Laguë, starting each party's
    divisor sequence at 2k+1 where k = baseline[party] (kredsmandater won).

    Used for national tillægsmandater allocation.
    """
    seats = {p: 0 for p in qualifying_votes}
    if n_tillaeg <= 0:
        return seats

    heap = []
    for party, votes in qualifying_votes.items():
        if votes > 0:
            k = baseline.get(party, 0)
            heapq.heappush(heap, (-votes / (2 * k + 1), party))

    for _ in range(n_tillaeg):
        if not heap:
            break
        _, party = heapq.heappop(heap)
        seats[party] += 1
        k = baseline.get(party, 0) + seats[party]
        heapq.heappush(heap, (-qualifying_votes[party] / (2 * k + 1), party))

    return seats
```

Also add `saint_lague_from_baseline` to the import in `tests/test_calculator.py`.

**Step 4: Run tests**

```bash
pytest tests/test_calculator.py -k "saint_lague_from_baseline" -v
```
Expected: all 4 pass.

**Step 5: Commit**

```bash
git add valg/calculator.py tests/test_calculator.py
git commit -m "feat: add saint_lague_from_baseline for proper tillæg calculation"
```

---

## Task 3: `allocate_kredsmandater_detail` and `allocate_tillaeg_to_storkredse`

`allocate_kredsmandater_detail` returns the per-storkreds breakdown (needed as input to the tillaeg storkreds assignment). `allocate_tillaeg_to_storkredse` assigns each party's national tillæg seats to storkredse.

**Files:**
- Modify: `valg/calculator.py`
- Test: `tests/test_calculator.py`

**Step 1: Write failing tests**

```python
from valg.calculator import allocate_kredsmandater_detail, allocate_tillaeg_to_storkredse

def test_allocate_kredsmandater_detail_structure():
    storkreds_votes = {
        "SK1": {"A": 1000, "B": 500},
        "SK2": {"A": 800, "B": 700},
    }
    result = allocate_kredsmandater_detail(storkreds_votes, {"SK1": 5, "SK2": 5})
    assert "SK1" in result and "SK2" in result
    assert sum(result["SK1"].values()) == 5
    assert sum(result["SK2"].values()) == 5

def test_allocate_kredsmandater_detail_totals_match_existing():
    storkreds_votes = {
        "SK1": {"A": 1000, "B": 500},
        "SK2": {"A": 800, "B": 700},
    }
    kredsmandater = {"SK1": 5, "SK2": 5}
    detail = allocate_kredsmandater_detail(storkreds_votes, kredsmandater)
    # Summing detail should match old allocate_kredsmandater
    totals = {}
    for sk_alloc in detail.values():
        for p, s in sk_alloc.items():
            totals[p] = totals.get(p, 0) + s
    assert totals == allocate_kredsmandater(storkreds_votes, kredsmandater)

def test_allocate_tillaeg_to_storkredse_total_per_party():
    storkreds_votes = {
        "SK1": {"A": 6000, "B": 2000},
        "SK2": {"A": 4000, "B": 3000},
    }
    kreds_detail = {
        "SK1": {"A": 3, "B": 1},
        "SK2": {"A": 2, "B": 1},
    }
    tillaeg_per_party = {"A": 3, "B": 1}
    result = allocate_tillaeg_to_storkredse(tillaeg_per_party, storkreds_votes, kreds_detail)
    assert sum(result["A"].values()) == 3
    assert sum(result["B"].values()) == 1

def test_allocate_tillaeg_to_storkredse_zero_tillaeg():
    result = allocate_tillaeg_to_storkredse(
        {"A": 0, "B": 2},
        {"SK1": {"A": 1000, "B": 500}},
        {"SK1": {"A": 2, "B": 1}},
    )
    assert result["A"] == {}
    assert sum(result["B"].values()) == 2
```

**Step 2: Run to verify failure**

```bash
pytest tests/test_calculator.py::test_allocate_kredsmandater_detail_structure -v
```
Expected: `FAILED` — `ImportError`

**Step 3: Implement**

Add to `valg/calculator.py` after `allocate_kredsmandater`:

```python
def allocate_kredsmandater_detail(
    storkreds_votes: dict[str, dict[str, int]],
    kredsmandater: dict[str, int],
) -> dict[str, dict[str, int]]:
    """
    D'Hondt kredsmandater allocation per storkreds.

    Returns:
        {storkreds_id: {party_id: seats}}
    """
    result = {}
    for sk_id, votes in storkreds_votes.items():
        n = kredsmandater.get(sk_id, 0)
        result[sk_id] = dhondt(votes, n) if n > 0 else {p: 0 for p in votes}
    return result


def allocate_tillaeg_to_storkredse(
    tillaeg_per_party: dict[str, int],
    storkreds_votes: dict[str, dict[str, int]],
    kreds_detail: dict[str, dict[str, int]],
) -> dict[str, dict[str, int]]:
    """
    Assign each party's national tillæg seats to storkredse via D'Hondt.

    Divisor for each storkreds starts at kreds_already_won_in_storkreds + 1.

    Returns:
        {party_id: {storkreds_id: tillaeg_seats_assigned}}
    """
    result = {}
    for party, n_tillaeg in tillaeg_per_party.items():
        if n_tillaeg <= 0:
            result[party] = {}
            continue

        party_sk_votes = {sk_id: votes.get(party, 0) for sk_id, votes in storkreds_votes.items()}
        party_sk_baseline = {sk_id: sk_alloc.get(party, 0) for sk_id, sk_alloc in kreds_detail.items()}

        result[party] = dhondt_from_baseline(party_sk_votes, party_sk_baseline, n_tillaeg)
    return result
```

Add imports to test file: `allocate_kredsmandater_detail, allocate_tillaeg_to_storkredse`.

**Step 4: Run tests**

```bash
pytest tests/test_calculator.py -k "detail or tillaeg_to_storkredse" -v
```
Expected: all 4 pass.

**Step 5: Commit**

```bash
git add valg/calculator.py tests/test_calculator.py
git commit -m "feat: add kredsmandater_detail and tillaeg storkreds assignment"
```

---

## Task 4: `allocate_seats_detail` and update `allocate_seats_total`

Introduce `allocate_seats_detail` (full per-party breakdown) and refactor `allocate_seats_total` to delegate to it. This is the only change to the existing public interface.

**Files:**
- Modify: `valg/calculator.py`
- Test: `tests/test_calculator.py`

**Step 1: Write failing tests**

```python
from valg.calculator import allocate_seats_detail

def test_allocate_seats_detail_structure():
    national_votes = {"A": 50000, "B": 30000, "C": 20000}
    storkreds_votes = {"SK1": {"A": 50000, "B": 30000, "C": 20000}}
    kredsmandater = {"SK1": 135}
    result = allocate_seats_detail(national_votes, storkreds_votes, kredsmandater)
    assert "A" in result
    assert {"kreds", "tillaeg", "total", "kreds_by_storkreds", "tillaeg_by_storkreds"} <= result["A"].keys()

def test_allocate_seats_detail_total_matches_total_function():
    national_votes = {"A": 50000, "B": 30000, "C": 20000}
    storkreds_votes = {"SK1": {"A": 50000, "B": 30000, "C": 20000}}
    kredsmandater = {"SK1": 135}
    detail = allocate_seats_detail(national_votes, storkreds_votes, kredsmandater)
    totals = allocate_seats_total(national_votes, storkreds_votes, kredsmandater)
    for party in national_votes:
        assert detail[party]["total"] == totals[party]

def test_allocate_seats_detail_kreds_plus_tillaeg_equals_total():
    national_votes = {"A": 50000, "B": 30000, "C": 20000}
    storkreds_votes = {"SK1": {"A": 50000, "B": 30000, "C": 20000}}
    kredsmandater = {"SK1": 135}
    result = allocate_seats_detail(national_votes, storkreds_votes, kredsmandater)
    for party, d in result.items():
        assert d["kreds"] + d["tillaeg"] == d["total"]

def test_allocate_seats_detail_tillaeg_by_storkreds_sums_to_tillaeg():
    national_votes = {"A": 50000, "B": 30000, "C": 20000}
    storkreds_votes = {"SK1": {"A": 50000, "B": 30000, "C": 20000}}
    kredsmandater = {"SK1": 135}
    result = allocate_seats_detail(national_votes, storkreds_votes, kredsmandater)
    for party, d in result.items():
        if d["tillaeg"] > 0:
            assert sum(d["tillaeg_by_storkreds"].values()) == d["tillaeg"]

def test_allocate_seats_total_uses_proper_baseline():
    # Sanity: total seats still sum to ≤ 175
    national_votes = {"A": 50000, "B": 30000, "C": 20000, "D": 500}
    storkreds_votes = {"SK1": national_votes}
    kredsmandater = {"SK1": 135}
    result = allocate_seats_total(national_votes, storkreds_votes, kredsmandater)
    assert sum(result.values()) <= 175
```

**Step 2: Run to verify failure**

```bash
pytest tests/test_calculator.py::test_allocate_seats_detail_structure -v
```
Expected: `FAILED` — `ImportError`

**Step 3: Implement**

Add to `valg/calculator.py` after `allocate_tillaeg_to_storkredse`, and replace `allocate_seats_total`:

```python
def allocate_seats_detail(
    national_votes: dict[str, int],
    storkreds_votes: dict[str, dict[str, int]],
    kredsmandater: dict[str, int],
) -> dict[str, dict]:
    """
    Full seat allocation with per-storkreds breakdown.

    Returns:
        {party_id: {
            "kreds": int,
            "tillaeg": int,
            "total": int,
            "kreds_by_storkreds": {storkreds_id: int},
            "tillaeg_by_storkreds": {storkreds_id: int},
        }}
    """
    kreds_detail = allocate_kredsmandater_detail(storkreds_votes, kredsmandater)

    kreds_won: dict[str, int] = {}
    for sk_alloc in kreds_detail.values():
        for party, s in sk_alloc.items():
            kreds_won[party] = kreds_won.get(party, 0) + s

    qualifying = _apply_threshold(national_votes, kreds_won)
    qualifying_votes = {p: v for p, v in national_votes.items() if p in qualifying}
    qualifying_kreds = {p: kreds_won.get(p, 0) for p in qualifying}

    tillaeg_per_party = saint_lague_from_baseline(qualifying_votes, qualifying_kreds, TILLAEG_SEATS)
    tillaeg_by_storkreds = allocate_tillaeg_to_storkredse(
        tillaeg_per_party, storkreds_votes, kreds_detail
    )

    result = {}
    for party in national_votes:
        kreds = kreds_won.get(party, 0)
        tillaeg = tillaeg_per_party.get(party, 0)
        kreds_by_sk = {sk_id: sk_alloc.get(party, 0) for sk_id, sk_alloc in kreds_detail.items()}
        result[party] = {
            "kreds": kreds,
            "tillaeg": tillaeg,
            "total": kreds + tillaeg,
            "kreds_by_storkreds": kreds_by_sk,
            "tillaeg_by_storkreds": tillaeg_by_storkreds.get(party, {}),
        }
    return result


def allocate_seats_total(
    national_votes: dict[str, int],
    storkreds_votes: dict[str, dict[str, int]],
    kredsmandater: dict[str, int],
) -> dict[str, int]:
    """
    Full seat allocation: kredsmandater (D'Hondt) + tillægsmandater (Sainte-Laguë from baseline).

    Args:
        national_votes: {party_id: total_votes_nationally}
        storkreds_votes: {storkreds_id: {party_id: votes}}
        kredsmandater: {storkreds_id: n_seats}

    Returns:
        {party_id: total_projected_seats} for all parties (0 if below threshold)
    """
    detail = allocate_seats_detail(national_votes, storkreds_votes, kredsmandater)
    return {p: d["total"] for p, d in detail.items()}
```

Remove the old `allocate_seats_total` body. Add `allocate_seats_detail` to the import in `tests/test_calculator.py`.

**Step 4: Run all calculator tests**

```bash
pytest tests/test_calculator.py -v
```
Expected: all existing + new tests pass.

**Step 5: Commit**

```bash
git add valg/calculator.py tests/test_calculator.py
git commit -m "feat: allocate_seats_detail with proper tillaeg + storkreds assignment"
```

---

## Task 5: `diff_seat_projections` in differ.py

Extends differ.py to compare two seat-detail snapshots and emit `seat_gained`, `seat_lost`, and `tillaeg_moved` events.

**Files:**
- Modify: `valg/differ.py`
- Test: `tests/test_differ.py`

**Step 1: Read existing differ.py**

```bash
cat valg/differ.py
cat tests/test_differ.py
```

**Step 2: Write failing tests**

Add to `tests/test_differ.py`:

```python
from valg.differ import diff_seat_projections

def test_diff_seat_projections_seat_gained():
    before = {"A": {"kreds": 5, "tillaeg": 2, "total": 7, "kreds_by_storkreds": {}, "tillaeg_by_storkreds": {}}}
    after  = {"A": {"kreds": 5, "tillaeg": 3, "total": 8, "kreds_by_storkreds": {}, "tillaeg_by_storkreds": {}}}
    events = diff_seat_projections(before, after)
    assert any(e["event_type"] == "seat_gained" and e["party_id"] == "A" for e in events)

def test_diff_seat_projections_seat_lost():
    before = {"A": {"kreds": 5, "tillaeg": 3, "total": 8, "kreds_by_storkreds": {}, "tillaeg_by_storkreds": {}}}
    after  = {"A": {"kreds": 5, "tillaeg": 2, "total": 7, "kreds_by_storkreds": {}, "tillaeg_by_storkreds": {}}}
    events = diff_seat_projections(before, after)
    assert any(e["event_type"] == "seat_lost" and e["party_id"] == "A" for e in events)

def test_diff_seat_projections_tillaeg_moved():
    before = {"A": {"kreds": 5, "tillaeg": 2, "total": 7, "kreds_by_storkreds": {}, "tillaeg_by_storkreds": {"SK1": 2, "SK2": 0}}}
    after  = {"A": {"kreds": 5, "tillaeg": 2, "total": 7, "kreds_by_storkreds": {}, "tillaeg_by_storkreds": {"SK1": 1, "SK2": 1}}}
    events = diff_seat_projections(before, after)
    assert any(e["event_type"] == "tillaeg_moved" and e["party_id"] == "A" for e in events)

def test_diff_seat_projections_no_change_no_events():
    snap = {"A": {"kreds": 5, "tillaeg": 2, "total": 7, "kreds_by_storkreds": {}, "tillaeg_by_storkreds": {"SK1": 2}}}
    events = diff_seat_projections(snap, snap)
    assert events == []

def test_diff_seat_projections_new_party():
    before = {}
    after  = {"A": {"kreds": 2, "tillaeg": 1, "total": 3, "kreds_by_storkreds": {}, "tillaeg_by_storkreds": {}}}
    events = diff_seat_projections(before, after)
    assert any(e["event_type"] == "seat_gained" and e["party_id"] == "A" for e in events)
```

**Step 3: Run to verify failure**

```bash
pytest tests/test_differ.py::test_diff_seat_projections_seat_gained -v
```
Expected: `FAILED` — `ImportError`

**Step 4: Implement**

Add to `valg/differ.py`:

```python
def diff_seat_projections(
    before: dict[str, dict],
    after: dict[str, dict],
) -> list[dict]:
    """
    Compare two seat-detail snapshots (from allocate_seats_detail).
    Returns a list of event dicts with keys: event_type, party_id, payload.

    event_type values:
      seat_gained  — party's total seats increased
      seat_lost    — party's total seats decreased
      tillaeg_moved — party's tillaeg redistribution changed (same count, different storkreds)
    """
    events = []
    all_parties = set(before) | set(after)

    for party in all_parties:
        b = before.get(party, {"total": 0, "tillaeg_by_storkreds": {}})
        a = after.get(party, {"total": 0, "tillaeg_by_storkreds": {}})

        b_total = b.get("total", 0)
        a_total = a.get("total", 0)

        if a_total > b_total:
            events.append({
                "event_type": "seat_gained",
                "party_id": party,
                "payload": {"before": b_total, "after": a_total},
            })
        elif a_total < b_total:
            events.append({
                "event_type": "seat_lost",
                "party_id": party,
                "payload": {"before": b_total, "after": a_total},
            })
        else:
            # Same total — check if tillaeg moved between storkredse
            b_sk = b.get("tillaeg_by_storkreds", {})
            a_sk = a.get("tillaeg_by_storkreds", {})
            if b_sk != a_sk:
                events.append({
                    "event_type": "tillaeg_moved",
                    "party_id": party,
                    "payload": {"before": b_sk, "after": a_sk},
                })

    return events
```

Add `diff_seat_projections` to the import in `tests/test_differ.py`.

**Step 5: Run all differ tests**

```bash
pytest tests/test_differ.py -v
```
Expected: all pass.

**Step 6: Commit**

```bash
git add valg/differ.py tests/test_differ.py
git commit -m "feat: diff_seat_projections emits seat_gained/lost/tillaeg_moved"
```

---

## Task 6: CLI — party command storkreds breakdown

The `party <party_id>` command should show kredsmandater and tillæg seats per storkreds, clearly labelled [PROJECTED].

**Files:**
- Read first: `valg/cli.py` (understand current party command)
- Read: `valg/models.py` (understand how to query storkreds names)
- Modify: `valg/cli.py`
- Test: `tests/test_cli.py` (or create if it doesn't exist)

**Step 1: Read the files**

```bash
cat valg/cli.py
cat valg/models.py
```
Look for `cmd_party` (or similar) and how storkreds data is queried.

**Step 2: Understand the current party command**

The party command currently shows total seat projection from `allocate_seats_total`. We need to:
1. Call `allocate_seats_detail` instead
2. Query storkreds names from the DB to map `storkreds_id → name`
3. Show a breakdown table: storkreds | kredsmandater | tillæg [PROJECTED]

**Step 3: Write failing test**

Look at `tests/test_cli.py` for the pattern used by existing party tests. Add:

```python
def test_cmd_party_shows_storkreds_breakdown(tmp_path):
    db = str(tmp_path / "test.db")
    conn = get_connection(db)
    init_db(conn)
    # Insert minimal fixture data: parties, storkredse, party_votes
    # ... (follow existing fixture pattern in test_cli.py)
    result = runner.invoke(app, ["--db", db, "party", "A"])
    assert "PROJECTED" in result.output or "storkreds" in result.output.lower()
```

Adapt to the actual test infrastructure once you've read the file.

**Step 4: Implement**

In `cmd_party` in `valg/cli.py`:
- Replace `allocate_seats_total(...)` call with `allocate_seats_detail(...)`
- Query storkreds names: `SELECT id, name FROM storkredse`
- Add a Rich table showing: Storkreds | Kredsmandater | Tillæg [PROJECTED]
- Show totals row at the bottom

**Step 5: Run tests**

```bash
pytest tests/test_cli.py -v
```
Expected: all pass.

**Step 6: Run the CLI manually to verify output**

```bash
python -m valg --db valg.db party A
```
(if data is available in local DB)

**Step 7: Commit**

```bash
git add valg/cli.py tests/test_cli.py
git commit -m "feat: party command shows storkreds tillæg breakdown [PROJECTED]"
```

---

## Task 7: CLI — status command kredsmandat/tillæg split

The `status` command currently shows `Total seats`. Add `Kredsmandat` and `Tillæg [PROJECTED]` columns.

**Files:**
- Modify: `valg/cli.py`
- Test: `tests/test_cli.py`

**Step 1: Write failing test**

Add to `tests/test_cli.py`:

```python
def test_cmd_status_shows_kreds_and_tillaeg_columns(tmp_path):
    # ... fixture setup (follow existing status test pattern)
    result = runner.invoke(app, ["--db", db, "status"])
    assert "Kreds" in result.output
    assert "Tillæg" in result.output
```

**Step 2: Run to verify failure**

```bash
pytest tests/test_cli.py::test_cmd_status_shows_kreds_and_tillaeg_columns -v
```
Expected: `FAILED`

**Step 3: Implement**

In `cmd_status` in `valg/cli.py`:
- Replace `allocate_seats_total(...)` with `allocate_seats_detail(...)`
- Replace the single `Seats` column with two columns: `Kreds` and `Tillæg [PROJ]`
- Keep total seats column as `Total`

**Step 4: Run all tests**

```bash
pytest -v
```
Expected: all pass.

**Step 5: Commit**

```bash
git add valg/cli.py tests/test_cli.py
git commit -m "feat: status command shows kreds/tillaeg split with [PROJ] label"
```

---

## Task 8: Final verification

**Step 1: Run full test suite with coverage**

```bash
pytest --cov=valg --cov-report=term-missing
```
Expected: all pass. Check coverage on calculator.py, differ.py — should be high.

**Step 2: Update CLAUDE.md seat calculation note**

In `valg/CLAUDE.md`, under `### Seat calculation`, replace the approximation note:

Old:
```
- **Tillægsmandater (40):** approximated via national modified Saint-Laguë minus kredsmandater. Good enough for seat-flip signalling; full calculation is v2.
```

New:
```
- **Tillægsmandater (40):** Sainte-Laguë with starting divisor 2k+1 where k = kredsmandater won per party. Storkreds assignment via D'Hondt from kredsmandat baseline. Labelled [PROJECTED] in output.
```

**Step 3: Commit final**

```bash
git add valg/CLAUDE.md
git commit -m "docs: update CLAUDE.md — proper tillæg calculation now implemented"
```
