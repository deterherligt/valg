# Candidate Breakdown in Party Detail Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the kredsmandater-by-storkreds table in the party detail panel with a candidate breakdown showing who is most likely to get in, with a visual cutoff line and vote margin (fintælling) or ballot-position order (preliminary); also remove candidate checkboxes and SVG arrows from the Om modal.

**Architecture:** Four independent changes applied in sequence — two pure removals (checkboxes, SVG arrows), one backend extension to `query_api_party_detail` that adds `candidates`/`has_votes`/`cutoff_margin` fields, and one frontend update that renders the new fields. The `seats_by_storkreds` field is kept in the API response but removed from the UI.

**Tech Stack:** Python/SQLite (`valg/queries.py`), Alpine.js (`valg/static/app.js`), HTML (`valg/templates/index.html`), CSS (`valg/static/app.css`), pytest with synthetic in-memory fixtures.

---

### Task 1: Remove candidate checkboxes

**Files:**
- Modify: `valg/static/app.js:3` (remove `selectedCandidateIds: []`)
- Modify: `valg/static/app.js:200-206` (remove `toggleCandidateCheck` method)
- Modify: `valg/templates/index.html:99-100` (remove checkbox input from candidate rows)

No test needed — pure dead-code removal. Verify nothing else references `selectedCandidateIds` or `toggleCandidateCheck` after the change.

- [ ] **Step 1: Remove `selectedCandidateIds` state from app.js**

In `valg/static/app.js`, remove line 3:
```diff
-    selectedCandidateIds: [],
```

- [ ] **Step 2: Remove `toggleCandidateCheck` method from app.js**

In `valg/static/app.js`, remove the entire `toggleCandidateCheck` method (lines 200-206):
```diff
-    toggleCandidateCheck(candidateId) {
-      if (this.selectedCandidateIds.includes(candidateId)) {
-        this.selectedCandidateIds = this.selectedCandidateIds.filter(id => id !== candidateId)
-      } else {
-        this.selectedCandidateIds = [...this.selectedCandidateIds, candidateId]
-      }
-    },
```

- [ ] **Step 3: Remove checkbox from candidate rows in index.html**

In `valg/templates/index.html`, remove lines 99-100:
```diff
-                <input type="checkbox" :checked="selectedCandidateIds.includes(c.id)"
-                       @click.stop="toggleCandidateCheck(c.id)">
```

- [ ] **Step 4: Verify no remaining references**

```bash
grep -n "selectedCandidateIds\|toggleCandidateCheck" valg/static/app.js valg/templates/index.html
```
Expected: no output.

- [ ] **Step 5: Commit**

```bash
git add valg/static/app.js valg/templates/index.html
git commit -m "remove unused candidate checkboxes"
```

---

### Task 2: Remove SVG arrows from Om modal

**Files:**
- Modify: `valg/templates/index.html:349-375` (remove `<svg class="about-arrows">` block)
- Modify: `valg/static/app.css:369-377` (remove `.about-arrows` rule)

No test needed — pure removal.

- [ ] **Step 1: Remove SVG block from index.html**

In `valg/templates/index.html`, remove lines 349-375 (the entire SVG element):
```diff
-  <!-- SVG annotation arrows (shown with about modal) -->
-  <svg class="about-arrows" x-show="showAbout"
-       viewBox="0 0 100 100" preserveAspectRatio="none"
-       xmlns="http://www.w3.org/2000/svg">
-    <defs>
-      <marker id="arrowhead" markerWidth="6" markerHeight="6"
-              refX="3" refY="3" orient="auto">
-        <path d="M0,0 L0,6 L6,3 Z" fill="#58a6ff" opacity="0.55"/>
-      </marker>
-    </defs>
-    <!-- Datakilder → header sync status (top-right area) -->
-    <path d="M 35,28 C 35,15 70,8 82,5"
-          stroke="#58a6ff" stroke-width="0.5" stroke-dasharray="1.5,1"
-          fill="none" marker-end="url(#arrowhead)" opacity="0.45"/>
-    <!-- Mandatberegning → parties col (left side) -->
-    <path d="M 22,42 C 10,42 6,52 5,62"
-          stroke="#58a6ff" stroke-width="0.5" stroke-dasharray="1.5,1"
-          fill="none" marker-end="url(#arrowhead)" opacity="0.45"/>
-    <!-- Kandidatoversigt → candidates col (centre) -->
-    <path d="M 40,50 C 30,58 30,68 32,72"
-          stroke="#58a6ff" stroke-width="0.5" stroke-dasharray="1.5,1"
-          fill="none" marker-end="url(#arrowhead)" opacity="0.45"/>
-    <!-- D'Hondt / detaljer → detail col (right) -->
-    <path d="M 62,42 C 72,42 78,52 80,62"
-          stroke="#58a6ff" stroke-width="0.5" stroke-dasharray="1.5,1"
-          fill="none" marker-end="url(#arrowhead)" opacity="0.45"/>
-  </svg>
```

- [ ] **Step 2: Remove `.about-arrows` CSS rule from app.css**

In `valg/static/app.css`, remove lines 369-377 (the `/* ── About arrows SVG */` block and `.about-arrows` rule):
```diff
-/* ── About arrows SVG ─────────────────────────────────────────── */
-.about-arrows {
-  position: fixed;
-  inset: 0;
-  width: 100vw;
-  height: 100vh;
-  z-index: 102;
-  pointer-events: none;
-  overflow: visible;
-}
```

- [ ] **Step 3: Verify no remaining references**

```bash
grep -n "about-arrows\|arrowhead" valg/templates/index.html valg/static/app.css
```
Expected: no output.

- [ ] **Step 4: Commit**

```bash
git add valg/templates/index.html valg/static/app.css
git commit -m "remove SVG arrows from Om modal"
```

---

### Task 3: Extend `query_api_party_detail` with candidate breakdown

**Files:**
- Modify: `valg/queries.py:224-278` (`query_api_party_detail`)
- Test: `tests/test_queries.py`

The function must add three new fields to each party object:
- `has_votes` — `True` if fintælling candidate data exists in `results`
- `candidates` — list of `{id, name, opstillingskreds, ballot_position, votes}`, sorted by `votes DESC` (fintælling) or `ballot_position ASC` (preliminary)
- `cutoff_margin` — `votes[seats_total-1] - votes[seats_total]` when `has_votes` and enough candidates, else `None`

- [ ] **Step 1: Write failing tests**

Add to `tests/test_queries.py`:

```python
from valg.queries import query_api_party_detail


def test_api_party_detail_candidates_preliminary(db_night):
    """During preliminary, candidates are sorted by ballot_position with has_votes=False."""
    party_id = db_night.execute("SELECT id FROM parties LIMIT 1").fetchone()[0]
    result = query_api_party_detail(db_night, [party_id])
    assert len(result) == 1
    p = result[0]
    assert "candidates" in p
    assert "has_votes" in p
    assert "cutoff_margin" in p
    assert p["has_votes"] is False
    assert p["cutoff_margin"] is None
    positions = [c["ballot_position"] for c in p["candidates"]]
    assert positions == sorted(positions)
    assert all(c["votes"] is None for c in p["candidates"])


def test_api_party_detail_candidates_final(db_final):
    """During fintælling, candidates sorted by votes DESC with cutoff_margin computed."""
    party_id = db_final.execute("SELECT id FROM parties LIMIT 1").fetchone()[0]
    result = query_api_party_detail(db_final, [party_id])
    assert len(result) == 1
    p = result[0]
    assert p["has_votes"] is True
    votes = [c["votes"] for c in p["candidates"] if c["votes"] is not None]
    assert votes == sorted(votes, reverse=True)
    seats = p["seats_total"]
    if seats >= 1 and len(p["candidates"]) > seats:
        assert p["cutoff_margin"] is not None
        assert p["cutoff_margin"] >= 0
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /Users/madsschmidt/Documents/valg && \
  .venv/bin/pytest tests/test_queries.py::test_api_party_detail_candidates_preliminary \
                   tests/test_queries.py::test_api_party_detail_candidates_final -v
```
Expected: FAIL with `KeyError: 'candidates'` or `AssertionError`.

- [ ] **Step 3: Implement the extension in `query_api_party_detail`**

Replace `valg/queries.py:224-278` with:

```python
def query_api_party_detail(conn, party_ids: list[str]) -> list[dict]:
    if not party_ids:
        return []

    national, storkreds_votes, kredsmandater = get_seat_data(conn)
    if not national:
        return []

    seats_alloc = calculator.allocate_seats_total(national, storkreds_votes, kredsmandater)
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

    # Check if fintælling candidate data exists (global for this election)
    has_votes = bool(
        conn.execute(
            "SELECT 1 FROM results WHERE candidate_id IS NOT NULL AND count_type = 'final' LIMIT 1"
        ).fetchone()
    )

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

        # Candidate breakdown
        if has_votes:
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
        else:
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

        # Cutoff margin: difference between last candidate in and first candidate out
        party_seats = seats_alloc.get(party_id, 0)
        cutoff_margin = None
        if has_votes and party_seats >= 1 and len(candidates) > party_seats:
            last_in = candidates[party_seats - 1]["votes"]
            first_out = candidates[party_seats]["votes"]
            if last_in is not None and first_out is not None:
                cutoff_margin = last_in - first_out

        info = party_rows.get(party_id, {"id": party_id, "letter": None, "name": party_id})
        result.append({
            "id": party_id,
            "letter": info["letter"],
            "name": info["name"],
            "votes": national[party_id],
            "pct": round(national[party_id] / total_votes * 100, 1),
            "seats_total": party_seats,
            "seats_by_storkreds": seats_breakdown,
            "candidates": candidates,
            "has_votes": has_votes,
            "cutoff_margin": cutoff_margin,
        })
    return result
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd /Users/madsschmidt/Documents/valg && \
  .venv/bin/pytest tests/test_queries.py::test_api_party_detail_candidates_preliminary \
                   tests/test_queries.py::test_api_party_detail_candidates_final -v
```
Expected: PASS.

- [ ] **Step 5: Run full test suite**

```bash
cd /Users/madsschmidt/Documents/valg && .venv/bin/pytest tests/ -v --ignore=tests/e2e
```
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add valg/queries.py tests/test_queries.py
git commit -m "extend query_api_party_detail with candidate breakdown and cutoff margin"
```

---

### Task 4: Update party detail panel UI

**Files:**
- Modify: `valg/templates/index.html:155-169` (replace `seats_by_storkreds` table)
- Modify: `valg/static/app.css` (add candidate cutoff styles)

Replace the storkreds kredsmandater table with a candidate list that shows who is likely to get in, with a visual cutoff line and margin.

- [ ] **Step 1: Add CSS for candidate breakdown**

In `valg/static/app.css`, append after the existing rules:

```css
/* ── Candidate breakdown in party detail ─────────────────────── */
.cand-breakdown-row {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  padding: 3px 0;
  font-size: 0.9em;
}
.cand-breakdown-row.cand-in  { color: #e6edf3; }
.cand-breakdown-row.cand-out { color: #8b949e; }
.cand-breakdown-name { flex: 1; }
.cand-breakdown-kreds { color: #484f58; font-size: 0.85em; margin-right: 8px; }
.cand-breakdown-votes { color: #3fb950; text-align: right; min-width: 60px; }
.cand-breakdown-row.cand-out .cand-breakdown-votes { color: #8b949e; }
.cand-cutoff {
  border-top: 1px dashed #388bfd44;
  margin: 4px 0;
  padding-top: 4px;
  font-size: 0.78em;
  color: #484f58;
}
.cand-breakdown-prelim-note {
  color: #8b949e;
  font-size: 0.85em;
  font-style: italic;
  padding: 4px 0 8px;
}
```

- [ ] **Step 2: Replace `seats_by_storkreds` table in index.html**

In `valg/templates/index.html`, find the party detail block (lines ~155-169) and replace:

```html
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
```

with:

```html
                      <!-- Candidate breakdown -->
                      <template x-if="!p.has_votes && p.candidates.length > 0">
                        <div>
                          <div class="cand-breakdown-prelim-note">Foreløbig rækkefølge — stemmetal tilgængeligt efter fintælling</div>
                          <template x-for="(c, i) in p.candidates" :key="c.id">
                            <div class="cand-breakdown-row" :class="i < p.seats_total ? 'cand-in' : 'cand-out'">
                              <span class="cand-breakdown-name" x-text="(i + 1) + '. ' + c.name"></span>
                              <span class="cand-breakdown-kreds" x-text="c.opstillingskreds"></span>
                            </div>
                          </template>
                        </div>
                      </template>
                      <template x-if="p.has_votes && p.candidates.length > 0">
                        <div>
                          <template x-for="(c, i) in p.candidates" :key="c.id">
                            <div>
                              <div x-show="i === p.seats_total" class="cand-cutoff"
                                   x-text="p.cutoff_margin !== null ? 'Grænse · ' + formatNum(p.cutoff_margin) + ' stemmer' : 'Grænse'">
                              </div>
                              <div class="cand-breakdown-row" :class="i < p.seats_total ? 'cand-in' : 'cand-out'">
                                <span class="cand-breakdown-name" x-text="c.name"></span>
                                <span class="cand-breakdown-kreds" x-text="c.opstillingskreds"></span>
                                <span class="cand-breakdown-votes" x-text="c.votes !== null ? formatNum(c.votes) : '—'"></span>
                              </div>
                            </div>
                          </template>
                        </div>
                      </template>
                      <template x-if="p.candidates.length === 0">
                        <div class="detail-placeholder" style="padding:8px 0">Ingen kandidater</div>
                      </template>
```

- [ ] **Step 3: Verify the page renders correctly**

Start the server (with the fv2022 demo scenario) and:
1. Select a party — the detail panel should show candidates sorted by votes with a dashed cutoff line and margin text
2. Open Om modal — no arrows should be visible
3. Check the candidate column — no checkboxes visible

```bash
cd /Users/madsschmidt/Documents/valg && python -m valg.server --demo
```

Open `http://localhost:5000` in a browser.

- [ ] **Step 4: Commit**

```bash
git add valg/templates/index.html valg/static/app.css
git commit -m "replace kredsmandater table with candidate breakdown panel"
```

---

### Task 5: Open PR

- [ ] **Step 1: Push branch and open PR**

```bash
git push -u origin HEAD
gh pr create \
  --title "Candidate breakdown in party detail panel" \
  --body "$(cat <<'EOF'
## Summary
- Replace kredsmandater-by-storkreds table with candidate breakdown showing who is likely to win seats
- During fintælling: candidates sorted by personal votes with dashed cutoff line and vote margin
- During preliminary: candidates in ballot order with a note that vote data arrives after fintælling
- Remove unused candidate checkboxes (selectedCandidateIds / toggleCandidateCheck)
- Remove SVG annotation arrows from Om modal

## Test plan
- [ ] `pytest tests/test_queries.py` passes including new `test_api_party_detail_candidates_*` tests
- [ ] Select party in fv2022 demo (fintælling phase) → candidate list with cutoff line visible
- [ ] Select party in preliminary phase → ballot-order list with italic note
- [ ] Open Om modal → no arrows visible
- [ ] Candidate column → no checkboxes

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```
