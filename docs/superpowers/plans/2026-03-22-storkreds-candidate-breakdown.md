# Per-Storkreds Candidate Breakdown Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Show each candidate's storkreds context (local rank + local seats) in the party detail panel so it is visible that a candidate with fewer personal votes can be elected because they run in a different district.

**Architecture:** Extend `query_api_party_detail` to join candidates to their storkreds, build a per-storkreds D'Hondt seat lookup, compute 1-based local ranks, and annotate each candidate dict with `storkreds`, `sk_rank`, `sk_seats`, and `elected`. The template switches fintælling row colouring from index-based to `c.elected` and adds a storkreds badge per candidate.

**Tech Stack:** Python, SQLite, Alpine.js (Jinja2 template), pytest.

**Spec:** `docs/superpowers/specs/2026-03-22-storkreds-candidate-breakdown-design.md`

---

## File Map

| File | Change |
|---|---|
| `valg/queries.py` | Extend `query_api_party_detail`: SQL joins, `sk_seats_for_party` dict, rank annotation loop |
| `valg/templates/index.html` | Fintælling: `c.elected` colouring + storkreds badge. Preliminary: add storkreds name |
| `tests/test_queries.py` | Four new tests for the new candidate fields |

---

### Task 1: Backend — storkreds fields in `query_api_party_detail`

**Files:**
- Modify: `valg/queries.py:261–312`
- Test: `tests/test_queries.py`

The function is at `valg/queries.py:224`. This task touches lines 261–312 (the per-party loop body).

**Background — how the existing loop works:**

```python
# Lines 261–273: builds seats_breakdown (kredsmandat per storkreds for this party)
seats_breakdown = []
for sk_id, sk_votes in storkreds_votes.items():
    n = kredsmandater.get(sk_id, 0)
    if n <= 0:
        continue
    sk_seats = calculator.dhondt(sk_votes, n)
    s = sk_seats.get(party_id, 0)
    if s > 0:
        seats_breakdown.append({"name": storkreds_names.get(sk_id, sk_id), "seats": s})

# Lines 276–301: fetches candidates (two branches: fintælling vs preliminary)
# Lines 303–312: builds candidates list of dicts
candidates = [{"id": r["id"], "name": ..., "opstillingskreds": ...,
                "ballot_position": ..., "votes": ...} for r in cand_rows]
```

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_queries.py` (after line 103):

```python
def test_api_party_detail_storkreds_fields_present(db_night):
    """All four storkreds fields are present on every candidate in preliminary."""
    party_id = db_night.execute("SELECT id FROM parties LIMIT 1").fetchone()[0]
    result = query_api_party_detail(db_night, [party_id])
    p = result[0]
    for c in p["candidates"]:
        assert "storkreds" in c, f"missing storkreds on {c['name']}"
        assert "sk_rank" in c, f"missing sk_rank on {c['name']}"
        assert "sk_seats" in c, f"missing sk_seats on {c['name']}"
        assert "elected" in c, f"missing elected on {c['name']}"
    # Preliminary: elected is always False
    assert all(c["elected"] is False for c in p["candidates"])


def test_api_party_detail_sk_rank_is_local(db_final):
    """sk_rank is 1-based and local to each storkreds, not global."""
    party_id = db_final.execute("SELECT id FROM parties LIMIT 1").fetchone()[0]
    result = query_api_party_detail(db_final, [party_id])
    p = result[0]
    # Group by storkreds, check ranks start at 1 and are contiguous
    from collections import defaultdict
    by_sk = defaultdict(list)
    for c in p["candidates"]:
        by_sk[c["storkreds"]].append(c["sk_rank"])
    for sk_name, ranks in by_sk.items():
        assert min(ranks) == 1, f"sk_rank does not start at 1 in {sk_name}"
        assert sorted(ranks) == list(range(1, len(ranks) + 1)), \
            f"sk_ranks not contiguous in {sk_name}: {sorted(ranks)}"


def test_api_party_detail_cross_storkreds_elected(tmp_path):
    """Core scenario: candidate elected with fewer votes because they are in a smaller storkreds."""
    from valg.models import get_connection, init_db
    conn = get_connection(":memory:")
    init_db(conn)

    # Two storkredse: SK_A gets 2 kredsmandater, SK_B gets 5
    conn.execute("INSERT OR REPLACE INTO storkredse (id, name, n_kredsmandater) VALUES ('SK_A','Storkreds A',2)")
    conn.execute("INSERT OR REPLACE INTO storkredse (id, name, n_kredsmandater) VALUES ('SK_B','Storkreds B',5)")
    conn.execute("INSERT OR REPLACE INTO opstillingskredse (id, name, storkreds_id) VALUES ('OK_A','Kreds A','SK_A')")
    conn.execute("INSERT OR REPLACE INTO opstillingskredse (id, name, storkreds_id) VALUES ('OK_B','Kreds B','SK_B')")
    conn.execute("INSERT OR REPLACE INTO parties (id, letter, name) VALUES ('A','A','Parti A')")

    # Candidates: two in SK_A, one in SK_B
    conn.execute("INSERT OR REPLACE INTO candidates (id, name, party_id, opstillingskreds_id, ballot_position) VALUES ('ca1','A1','A','OK_A',1)")
    conn.execute("INSERT OR REPLACE INTO candidates (id, name, party_id, opstillingskreds_id, ballot_position) VALUES ('ca2','A2','A','OK_A',2)")
    conn.execute("INSERT OR REPLACE INTO candidates (id, name, party_id, opstillingskreds_id, ballot_position) VALUES ('cb1','B1','A','OK_B',1)")

    snap = "2024-11-05T22:00:00"
    # Party votes: 1000 in SK_A, 0 in SK_B → D'Hondt gives party 2 seats in SK_A, 0 in SK_B
    conn.execute("INSERT INTO party_votes (opstillingskreds_id,party_id,votes,snapshot_at) VALUES ('OK_A','A',1000,?)", (snap,))

    # Fintælling results — B1 has more votes than A2, but B1 is in SK_B (0 seats)
    for cand_id, votes in [("ca1", 600), ("ca2", 300), ("cb1", 800)]:
        conn.execute(
            "INSERT INTO results (candidate_id,party_id,votes,count_type,snapshot_at) "
            "VALUES (?,?,?,'final',?)",
            (cand_id, "A", votes, snap),
        )
    conn.commit()

    result = query_api_party_detail(conn, ["A"])
    assert len(result) == 1
    p = result[0]
    by_id = {c["id"]: c for c in p["candidates"]}

    # A2 has fewer votes than B1 but is elected (SK_A has 2 seats, A2 is ranked #2)
    assert by_id["ca2"]["elected"] is True,  "A2 should be elected (SK_A seat #2)"
    assert by_id["cb1"]["elected"] is False, "B1 should not be elected (SK_B has 0 seats for party)"
    assert by_id["ca2"]["sk_rank"] == 2
    assert by_id["ca2"]["sk_seats"] == 2
    assert by_id["cb1"]["sk_rank"] == 1
    assert by_id["cb1"]["sk_seats"] == 0


def test_api_party_detail_zero_seat_storkreds(tmp_path):
    """Candidates in a storkreds where party wins 0 seats have sk_seats=0 and elected=False."""
    from valg.models import get_connection, init_db
    conn = get_connection(":memory:")
    init_db(conn)

    conn.execute("INSERT OR REPLACE INTO storkredse (id, name, n_kredsmandater) VALUES ('SK_X','Storkreds X',3)")
    conn.execute("INSERT OR REPLACE INTO opstillingskredse (id, name, storkreds_id) VALUES ('OK_X','Kreds X','SK_X')")
    conn.execute("INSERT OR REPLACE INTO parties (id, letter, name) VALUES ('B','B','Parti B')")
    conn.execute("INSERT OR REPLACE INTO parties (id, letter, name) VALUES ('C','C','Parti C')")
    conn.execute("INSERT OR REPLACE INTO candidates (id, name, party_id, opstillingskreds_id, ballot_position) VALUES ('bx1','BX1','B','OK_X',1)")
    snap = "2024-11-05T22:00:00"
    # Party B has small votes; party C dominates — D'Hondt gives all 3 seats to C, 0 to B
    conn.execute("INSERT INTO party_votes (opstillingskreds_id,party_id,votes,snapshot_at) VALUES ('OK_X','B',100,?)", (snap,))
    conn.execute("INSERT INTO party_votes (opstillingskreds_id,party_id,votes,snapshot_at) VALUES ('OK_X','C',5000,?)", (snap,))
    conn.execute(
        "INSERT INTO results (candidate_id,party_id,votes,count_type,snapshot_at) "
        "VALUES ('bx1','B',500,'final',?)", (snap,)
    )
    conn.commit()

    result = query_api_party_detail(conn, ["B"])
    assert len(result) == 1
    c = result[0]["candidates"][0]
    assert c["sk_seats"] == 0
    assert c["elected"] is False
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /Users/madsschmidt/Documents/valg && \
  .venv/bin/pytest tests/test_queries.py::test_api_party_detail_storkreds_fields_present \
                   tests/test_queries.py::test_api_party_detail_sk_rank_is_local \
                   tests/test_queries.py::test_api_party_detail_cross_storkreds_elected \
                   tests/test_queries.py::test_api_party_detail_zero_seat_storkreds -v
```
Expected: FAIL with `KeyError: 'storkreds'` or `AssertionError`.

- [ ] **Step 3: Implement — extend the D'Hondt loop**

In `valg/queries.py`, find the `seats_breakdown = []` block inside the per-party `for party_id in party_ids:` loop (around line 262). Replace:

```python
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
```

With:

```python
        # Kredsmandater breakdown per storkreds (D'Hondt per storkreds)
        sk_seats_for_party: dict[str, int] = {}  # sk_id → kredsmandat seats for this party
        seats_breakdown = []
        for sk_id, sk_votes in storkreds_votes.items():
            n = kredsmandater.get(sk_id, 0)
            if n <= 0:
                continue
            sk_seats_map = calculator.dhondt(sk_votes, n)
            s = sk_seats_map.get(party_id, 0)
            sk_seats_for_party[sk_id] = s
            if s > 0:
                seats_breakdown.append({
                    "name": storkreds_names.get(sk_id, sk_id),
                    "seats": s,
                })
```

- [ ] **Step 4: Implement — extend the SQL queries**

In `valg/queries.py`, find the fintælling SQL (inside `if has_votes:`, around line 277). Replace:

```python
            cand_rows = conn.execute(
                """
                SELECT c.id, c.name, ok.name AS opstillingskreds, c.ballot_position,
                       SUM(r.votes) AS votes
                FROM candidates c
                JOIN opstillingskredse ok ON ok.id = c.opstillingskreds_id
                JOIN results r ON r.candidate_id = c.id
                WHERE c.party_id = ? AND r.count_type = 'final'
                GROUP BY c.id
                ORDER BY votes DESC
                """,
                (party_id,),
            ).fetchall()
```

With:

```python
            cand_rows = conn.execute(
                """
                SELECT c.id, c.name, ok.name AS opstillingskreds, c.ballot_position,
                       SUM(r.votes) AS votes, ok.storkreds_id, sk.name AS storkreds_name
                FROM candidates c
                JOIN opstillingskredse ok ON ok.id = c.opstillingskreds_id
                JOIN storkredse sk ON sk.id = ok.storkreds_id
                JOIN results r ON r.candidate_id = c.id
                WHERE c.party_id = ? AND r.count_type = 'final'
                GROUP BY c.id
                ORDER BY votes DESC
                """,
                (party_id,),
            ).fetchall()
```

Find the preliminary SQL (inside `else:`, around line 291). Replace:

```python
            cand_rows = conn.execute(
                """
                SELECT c.id, c.name, ok.name AS opstillingskreds, c.ballot_position,
                       NULL AS votes
                FROM candidates c
                JOIN opstillingskredse ok ON ok.id = c.opstillingskreds_id
                WHERE c.party_id = ?
                ORDER BY c.ballot_position
                """,
                (party_id,),
            ).fetchall()
```

With:

```python
            cand_rows = conn.execute(
                """
                SELECT c.id, c.name, ok.name AS opstillingskreds, c.ballot_position,
                       NULL AS votes, ok.storkreds_id, sk.name AS storkreds_name
                FROM candidates c
                JOIN opstillingskredse ok ON ok.id = c.opstillingskreds_id
                JOIN storkredse sk ON sk.id = ok.storkreds_id
                WHERE c.party_id = ?
                ORDER BY c.ballot_position
                """,
                (party_id,),
            ).fetchall()
```

- [ ] **Step 5: Implement — build candidates list and annotate ranks**

Find the `candidates = [...]` list comprehension (around line 303). Replace:

```python
        candidates = [
            {
                "id": r["id"],
                "name": r["name"],
                "opstillingskreds": r["opstillingskreds"],
                "ballot_position": r["ballot_position"],
                "votes": r["votes"],
            }
            for r in cand_rows
        ]
```

With:

```python
        candidates = [
            {
                "id": r["id"],
                "name": r["name"],
                "opstillingskreds": r["opstillingskreds"],
                "ballot_position": r["ballot_position"],
                "votes": r["votes"],
                "storkreds": r["storkreds_name"],
                "_sk_id": r["storkreds_id"],
            }
            for r in cand_rows
        ]

        # Annotate each candidate with per-storkreds rank and election status.
        # Candidates are already in national order (votes DESC or ballot_position ASC).
        # Ranks are computed within each storkreds independently.
        from collections import defaultdict
        sk_groups: dict = defaultdict(list)
        for c in candidates:
            sk_groups[c["_sk_id"]].append(c)

        for sk_id, group in sk_groups.items():
            sk_party_seats = sk_seats_for_party.get(sk_id, 0)
            if has_votes:
                ranked = sorted(group, key=lambda c: (c["votes"] or 0), reverse=True)
            else:
                ranked = sorted(group, key=lambda c: c["ballot_position"])
            for rank, c in enumerate(ranked, 1):
                c["sk_rank"] = rank
                c["sk_seats"] = sk_party_seats
                c["elected"] = has_votes and rank <= sk_party_seats

        for c in candidates:
            del c["_sk_id"]
```

- [ ] **Step 6: Run the new tests**

```bash
cd /Users/madsschmidt/Documents/valg && \
  .venv/bin/pytest tests/test_queries.py::test_api_party_detail_storkreds_fields_present \
                   tests/test_queries.py::test_api_party_detail_sk_rank_is_local \
                   tests/test_queries.py::test_api_party_detail_cross_storkreds_elected \
                   tests/test_queries.py::test_api_party_detail_zero_seat_storkreds -v
```
Expected: all PASS.

- [ ] **Step 7: Run full suite**

```bash
cd /Users/madsschmidt/Documents/valg && .venv/bin/pytest tests/ --ignore=tests/e2e -q
```
Expected: all pass.

- [ ] **Step 8: Commit**

```bash
git add valg/queries.py tests/test_queries.py
git commit -m "feat: add per-storkreds rank and elected status to party detail candidates"
```

---

### Task 2: Frontend — storkreds badge and updated colouring

**Files:**
- Modify: `valg/templates/index.html:154–180`

No new tests (visual correctness verified manually).

**Background — current template structure:**

The fintælling block is at `x-if="p.has_votes && p.candidates.length > 0"` (~line 165). The preliminary block is at `x-if="!p.has_votes && p.candidates.length > 0"` (~line 154).

Fintælling row (current):
```html
<div class="cand-breakdown-row" :class="i < p.seats_total ? 'cand-in' : 'cand-out'">
  <span class="cand-breakdown-name" x-text="c.name"></span>
  <span class="cand-breakdown-kreds" x-text="c.opstillingskreds"></span>
  <span class="cand-breakdown-votes" x-text="c.votes !== null ? formatNum(c.votes) : '—'"></span>
</div>
```

Preliminary row (current):
```html
<div class="cand-breakdown-row" :class="i < p.seats_total ? 'cand-in' : 'cand-out'">
  <span class="cand-breakdown-name" x-text="(i + 1) + '. ' + c.name"></span>
  <span class="cand-breakdown-kreds" x-text="c.opstillingskreds"></span>
</div>
```

- [ ] **Step 1: Update fintælling colouring and add storkreds badge**

In `valg/templates/index.html`, find the fintælling `cand-breakdown-row` div (the one inside `x-if="p.has_votes"`). Replace:

```html
                              <div class="cand-breakdown-row" :class="i < p.seats_total ? 'cand-in' : 'cand-out'">
                                <span class="cand-breakdown-name" x-text="c.name"></span>
                                <span class="cand-breakdown-kreds" x-text="c.opstillingskreds"></span>
                                <span class="cand-breakdown-votes" x-text="c.votes !== null ? formatNum(c.votes) : '—'"></span>
                              </div>
```

With:

```html
                              <div class="cand-breakdown-row" :class="c.elected ? 'cand-in' : 'cand-out'">
                                <span class="cand-breakdown-name" x-text="c.name"></span>
                                <span class="cand-breakdown-kreds" x-text="c.opstillingskreds"></span>
                                <span class="cand-breakdown-sk"
                                      x-text="c.sk_seats > 0 ? '#' + c.sk_rank + ' i ' + c.storkreds + ' (' + c.sk_seats + ' mandater)' : '#' + c.sk_rank + ' i ' + c.storkreds">
                                </span>
                                <span class="cand-breakdown-votes" x-text="c.votes !== null ? formatNum(c.votes) : '—'"></span>
                              </div>
```

- [ ] **Step 2: Add storkreds to preliminary rows**

In the preliminary block (`x-if="!p.has_votes"`), find the preliminary `cand-breakdown-row` div. Replace:

```html
                            <div class="cand-breakdown-row" :class="i < p.seats_total ? 'cand-in' : 'cand-out'">
                              <span class="cand-breakdown-name" x-text="(i + 1) + '. ' + c.name"></span>
                              <span class="cand-breakdown-kreds" x-text="c.opstillingskreds"></span>
                            </div>
```

With:

```html
                            <div class="cand-breakdown-row" :class="i < p.seats_total ? 'cand-in' : 'cand-out'">
                              <span class="cand-breakdown-name" x-text="(i + 1) + '. ' + c.name"></span>
                              <span class="cand-breakdown-kreds" x-text="c.opstillingskreds + ' · ' + c.storkreds"></span>
                            </div>
```

- [ ] **Step 3: Add CSS for the new badge span**

In `valg/static/app.css`, find the `.cand-breakdown-kreds` rule. After it, add:

```css
.cand-breakdown-sk {
  color: #60a5fa;
  font-size: 0.78em;
  opacity: 0.85;
  white-space: nowrap;
}
```

- [ ] **Step 4: Run full suite to confirm no regressions**

```bash
cd /Users/madsschmidt/Documents/valg && .venv/bin/pytest tests/ --ignore=tests/e2e -q
```
Expected: all pass.

- [ ] **Step 5: Manual smoke test**

Start the server with fv2022 running:
```bash
cd /Users/madsschmidt/Documents/valg && .venv/bin/python -m valg.server --demo
```
Open `http://localhost:5000`, start the fv2022 demo at high speed, select a party. After fintælling waves arrive, verify:
- Candidate rows are interleaved green/grey (not cleanly separated)
- Each row shows a blue `#N i [Storkreds] (M mandater)` badge
- The national cutoff line still appears at position `seats_total`
- Preliminary rows show `Opstillingskreds · Storkreds`

- [ ] **Step 6: Commit**

```bash
git add valg/templates/index.html valg/static/app.css
git commit -m "feat: show storkreds rank badge and per-storkreds elected colouring"
```

---

### Task 3: Open PR

- [ ] **Step 1: Push and open PR**

```bash
git push -u origin HEAD
gh pr create \
  --title "Per-storkreds candidate breakdown" \
  --body "$(cat <<'EOF'
## Summary
- Each candidate in the party detail panel now shows their storkreds context: `#N i [Storkreds] (M mandater)`
- Fintælling row colouring switches from national rank to per-storkreds kredsmandat election status
- Makes the core mechanic visible: a Bornholm candidate with 891 votes can appear green between Copenhagen candidates with 3,000+ votes who are grey, because seats are allocated per storkreds
- Preliminary rows gain storkreds name as informational label
- National cutoff line and seats_total unchanged

## Test plan
- [ ] `pytest tests/test_queries.py` — four new tests including the cross-storkreds scenario
- [ ] Run fv2022 demo, select a party, verify interleaved green/grey with storkreds badges after fintælling

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```
