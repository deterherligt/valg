# Storkreds Filter & Elected/Bubble View Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add storkreds-grouped filtering to the candidates column and an elected/bubble breakdown view in the party detail panel.

**Architecture:** Backend adds `storkreds` + `storkreds_id` fields to `/api/candidates` via a single JOIN. Frontend replaces the party-grouped candidates list with a storkreds-grouped one; clicking a storkreds header sets `activeStorkreds` state which filters both the candidates column and switches the detail panel to an elected/bubble view computed client-side from existing `partyDetail` data.

**Tech Stack:** Python/Flask, SQLite, Alpine.js (CDN), vanilla JS, CSS

---

## File Map

| File | Change |
|------|--------|
| `valg/queries.py` | Add JOIN + 2 fields to `query_api_candidates` |
| `tests/test_queries.py` | Test new fields on `query_api_candidates` |
| `tests/test_server.py` | Test `/api/candidates` endpoint returns `storkreds` fields |
| `valg/static/app.js` | Add `activeStorkreds` state, replace `candidatesByParty` getter, add `candidatesByStorkreds` + `storkredsCandidateBlocks`, update `toggleParty`, add `selectStorkreds` method |
| `valg/templates/index.html` | Candidates column: storkreds group headers + content; Detail panel: storkreds elected/bubble view |
| `valg/static/app.css` | Styles for storkreds header row, active indicator, elected/bubble section labels |

---

## Task 1: Backend — add `storkreds` and `storkreds_id` to `/api/candidates`

**Files:**
- Modify: `valg/queries.py`
- Modify: `tests/test_queries.py`
- Modify: `tests/test_server.py`

- [ ] **Step 1: Write the failing test in `tests/test_queries.py`**

Add this test after the existing tests. The `db_night` fixture is already defined there.

```python
def test_api_candidates_storkreds_fields(db_night):
    """query_api_candidates returns storkreds and storkreds_id on every candidate."""
    party_id = db_night.execute("SELECT id FROM parties LIMIT 1").fetchone()[0]
    from valg.queries import query_api_candidates
    rows = query_api_candidates(db_night, [party_id])
    assert len(rows) > 0
    for r in rows:
        assert "storkreds" in r, f"missing storkreds on {r['name']}"
        assert "storkreds_id" in r, f"missing storkreds_id on {r['name']}"
        assert isinstance(r["storkreds"], str)
        assert isinstance(r["storkreds_id"], str)
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_queries.py::test_api_candidates_storkreds_fields -v
```

Expected: `FAILED — KeyError: 'storkreds'`

- [ ] **Step 3: Implement in `valg/queries.py`**

Replace `query_api_candidates` (lines ~209–223):

```python
def query_api_candidates(conn, party_ids: list[str]) -> list[dict]:
    if not party_ids:
        return []
    placeholders = ",".join("?" * len(party_ids))
    rows = conn.execute(
        f"SELECT c.id, c.name, c.party_id, p.letter as party_letter, "
        f"ok.name as opstillingskreds, c.ballot_position, "
        f"sk.name as storkreds, sk.id as storkreds_id "
        f"FROM candidates c "
        f"JOIN parties p ON c.party_id = p.id "
        f"JOIN opstillingskredse ok ON c.opstillingskreds_id = ok.id "
        f"JOIN storkredse sk ON sk.id = ok.storkreds_id "
        f"WHERE c.party_id IN ({placeholders}) "
        f"ORDER BY sk.name, c.party_id, c.ballot_position",
        party_ids,
    ).fetchall()
    return [dict(r) for r in rows]
```

Note: ORDER BY changed to `sk.name, c.party_id, c.ballot_position` — groups by storkreds first, consistent with how the frontend will render them.

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/test_queries.py::test_api_candidates_storkreds_fields -v
```

Expected: `PASSED`

- [ ] **Step 5: Write failing server test in `tests/test_server.py`**

Add after the existing `/api/candidates` test (or at the bottom of the file):

```python
def test_api_candidates_includes_storkreds_fields(client_with_data):
    """GET /api/candidates returns storkreds and storkreds_id fields."""
    import json
    # Get a real party_id from the db
    from valg.models import get_connection, init_db
    # Fetch party list first to get a valid id
    resp = client_with_data.get("/api/parties")
    parties = json.loads(resp.data)
    assert len(parties) > 0
    party_id = parties[0]["id"]

    resp = client_with_data.get(f"/api/candidates?party_ids={party_id}")
    assert resp.status_code == 200
    rows = json.loads(resp.data)
    assert len(rows) > 0
    assert "storkreds" in rows[0]
    assert "storkreds_id" in rows[0]
```

- [ ] **Step 6: Run test to verify it passes** (backend change already in place)

```bash
pytest tests/test_server.py::test_api_candidates_includes_storkreds_fields -v
```

Expected: `PASSED`

- [ ] **Step 7: Run full test suite to confirm no regressions**

```bash
pytest tests/test_queries.py tests/test_server.py -v
```

Expected: all green

- [ ] **Step 8: Commit**

```bash
git add valg/queries.py tests/test_queries.py tests/test_server.py
git commit -m "feat: add storkreds and storkreds_id fields to /api/candidates"
```

---

## Task 2: Frontend JS — `activeStorkreds` state, `candidatesByStorkreds`, `storkredsCandidateBlocks`, `selectStorkreds`, updated `toggleParty`

**Files:**
- Modify: `valg/static/app.js`

No automated tests for Alpine.js logic — correctness verified through Task 3 (HTML) and manual smoke test.

- [ ] **Step 1: Add `activeStorkreds` to state (top of `Alpine.data` object)**

In `valg/static/app.js`, add after `selectedPartyIds: [],` (line 3):

```js
activeStorkreds: null,  // { id: string, name: string } | null
```

- [ ] **Step 2: Replace `candidatesByParty` getter with `candidatesByStorkreds`**

Replace the entire `get candidatesByParty()` block (~lines 210–219):

```js
get candidatesByStorkreds() {
  // Group candidates by storkreds_id, preserving order returned by API
  // (already ordered sk.name, party_id, ballot_position)
  const groups = []
  const seen = {}
  for (const c of this.candidates) {
    const key = c.storkreds_id
    if (!seen[key]) {
      seen[key] = { storkreds_id: c.storkreds_id, storkreds: c.storkreds, candidates: [] }
      groups.push(seen[key])
    }
    seen[key].candidates.push(c)
  }
  return groups
},
```

- [ ] **Step 3: Add `storkredsCandidateBlocks` computed getter** (after `candidatesByStorkreds`)

This drives the detail panel's storkreds view. Add after `candidatesByStorkreds`:

```js
get storkredsCandidateBlocks() {
  if (!this.activeStorkreds || !this.partyDetail) return []
  return this.partyDetail.map(p => {
    const cands = p.candidates
      .filter(c => c.storkreds === this.activeStorkreds.name)
      .sort((a, b) => a.sk_rank - b.sk_rank)
    const skSeats = cands.length > 0 ? cands[0].sk_seats : 0
    const elected = cands.filter(c => c.sk_rank <= skSeats)
    const bubble = cands.filter(c => c.sk_rank > skSeats)
    const lastElectedVotes = elected.length > 0 ? elected[elected.length - 1].votes : null
    return {
      party_id: p.id,
      letter: p.letter,
      name: p.name,
      sk_seats: skSeats,
      has_votes: p.has_votes,
      elected,
      bubble: bubble.map(c => ({
        ...c,
        mangler: (skSeats > 0 && lastElectedVotes !== null && c.votes !== null)
          ? lastElectedVotes - c.votes + 1
          : null,
      })),
      empty: cands.length === 0,
    }
  })
},
```

- [ ] **Step 4: Add `selectStorkreds` method** (after `focusCandidate`)

```js
selectStorkreds(storkreds_id, storkreds_name) {
  if (this.activeStorkreds && this.activeStorkreds.id === storkreds_id) {
    this.activeStorkreds = null
  } else {
    this.activeStorkreds = { id: storkreds_id, name: storkreds_name }
  }
},
```

- [ ] **Step 5: Update `toggleParty` to clear `activeStorkreds` when last party deselected**

In `toggleParty`, in the branch that removes a party (`this.selectedPartyIds = this.selectedPartyIds.filter(...)`), add after the filter line:

```js
if (this.selectedPartyIds.length === 0) {
  this.activeStorkreds = null
}
```

The final `toggleParty` deselect branch should look like:

```js
if (this.selectedPartyIds.includes(partyId)) {
  this.selectedPartyIds = this.selectedPartyIds.filter(id => id !== partyId)
  if (this.selectedPartyIds.length === 0) {
    this.activeStorkreds = null
  }
  // Clear focused candidate if their party was deselected
  if (this.focusedCandidateId) {
    const fc = this.candidates.find(c => c.id === this.focusedCandidateId)
    if (fc && fc.party_id === partyId) {
      this.focusedCandidateId = null
      this.candidateDetail = null
      this.candidateFeed = []
    }
  }
}
```

- [ ] **Step 6: Commit**

```bash
git add valg/static/app.js
git commit -m "feat: storkreds filter state, candidatesByStorkreds getter, storkredsCandidateBlocks"
```

---

## Task 3: Frontend HTML — candidates column + detail panel

**Files:**
- Modify: `valg/templates/index.html`

- [ ] **Step 1: Replace candidates column body in `index.html`**

Find the candidates column body (`<div class="col-body">` inside `.col-candidates`, lines ~94–116). Replace the entire inner content with:

```html
<div class="col-body">
  <template x-if="selectedPartyIds.length === 0">
    <div class="detail-placeholder" style="padding:16px 12px;color:#8b949e">
      Select a party
    </div>
  </template>
  <template x-if="selectedPartyIds.length > 0 && candidates.length === 0">
    <div class="detail-placeholder" style="padding:16px 12px;color:#8b949e">
      Loading…
    </div>
  </template>
  <template x-if="selectedPartyIds.length > 0 && candidates.length > 0">
    <div>
      <!-- Check if active storkreds has any candidates -->
      <template x-if="activeStorkreds && candidatesByStorkreds.filter(g => g.storkreds_id === activeStorkreds.id).length === 0">
        <div class="detail-placeholder" style="padding:16px 12px;color:#8b949e">
          Ingen kandidater i denne storkreds
        </div>
      </template>
      <template x-for="group in candidatesByStorkreds" :key="group.storkreds_id">
        <div>
          <div class="sk-group-header"
               :class="{ 'sk-group-header--active': activeStorkreds && activeStorkreds.id === group.storkreds_id }"
               @click="selectStorkreds(group.storkreds_id, group.storkreds)">
            <span x-show="activeStorkreds && activeStorkreds.id === group.storkreds_id"
                  class="sk-active-indicator">▸ </span>
            <span x-text="group.storkreds"></span>
          </div>
          <template x-if="!activeStorkreds || activeStorkreds.id === group.storkreds_id">
            <div>
              <template x-for="c in group.candidates" :key="c.id">
                <div class="candidate-row"
                     :class="{focused: focusedCandidateId === c.id}"
                     @click="focusCandidate(c.id)">
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
      </template>
    </div>
  </template>
</div>
```

- [ ] **Step 2: Update the candidates column header**

The existing header reads `<span x-show="selectedPartyIds.length > 0" x-text="'Candidates — ' + selectedPartyLetters"></span>`. Also add a storkreds indicator:

```html
<div class="col-header">
  <span x-show="selectedPartyIds.length === 0">Candidates</span>
  <span x-show="selectedPartyIds.length > 0 && !activeStorkreds"
        x-text="'Candidates — ' + selectedPartyLetters"></span>
  <span x-show="selectedPartyIds.length > 0 && activeStorkreds"
        x-text="'Candidates — ' + selectedPartyLetters + ' · ' + (activeStorkreds ? activeStorkreds.name : '')"></span>
</div>
```

- [ ] **Step 3: Add storkreds elected/bubble view to the detail panel**

In the detail panel, inside `<div x-show="activeTab !== 'sted'">`, the current structure is:

```html
<!-- Party detail mode -->
<template x-if="!focusedCandidateId">
  <div>
    ...national view...
  </div>
</template>
```

Replace the inner content of `<template x-if="!focusedCandidateId">` with:

```html
<template x-if="!focusedCandidateId">
  <div>
    <template x-if="!selectedPartyIds.length">
      <div class="detail-placeholder">Select a party to see details</div>
    </template>
    <template x-if="selectedPartyIds.length && !partyDetail">
      <div class="detail-placeholder">Loading…</div>
    </template>

    <!-- Storkreds elected/bubble view (when a storkreds is active) -->
    <template x-if="partyDetail && activeStorkreds">
      <div>
        <div class="sk-detail-heading" x-text="activeStorkreds.name"></div>
        <template x-for="block in storkredsCandidateBlocks" :key="block.party_id">
          <div class="party-detail-block">
            <div class="party-detail-name"
                 x-text="(block.letter || block.party_id) + ' — ' + block.name + ' — ' + block.sk_seats + ' mandater'">
            </div>
            <template x-if="block.empty">
              <div class="detail-placeholder" style="padding:8px 0">Ingen kandidater i denne storkreds</div>
            </template>
            <template x-if="!block.empty">
              <div>
                <!-- Elected section (shown even if empty, unless sk_seats === 0) -->
                <template x-if="block.sk_seats > 0">
                  <div class="sk-section-label">Valgte</div>
                </template>
                <template x-for="c in block.elected" :key="c.id">
                  <div class="cand-breakdown-row cand-in">
                    <span class="cand-breakdown-name" x-text="c.sk_rank + '. ' + c.name"></span>
                    <span class="cand-breakdown-kreds" x-text="c.opstillingskreds"></span>
                    <span class="cand-breakdown-votes"
                          x-text="c.votes !== null ? formatNum(c.votes) : ''"></span>
                  </div>
                </template>
                <!-- Bubble section -->
                <template x-if="block.bubble.length > 0">
                  <div class="sk-section-label">Ikke valgt</div>
                </template>
                <template x-for="c in block.bubble" :key="c.id">
                  <div class="cand-breakdown-row cand-out">
                    <span class="cand-breakdown-name" x-text="c.sk_rank + '. ' + c.name"></span>
                    <span class="cand-breakdown-kreds" x-text="c.opstillingskreds"></span>
                    <span class="cand-breakdown-votes"
                          x-text="c.votes !== null ? formatNum(c.votes) : ''"></span>
                    <span class="cand-breakdown-mangler"
                          x-show="block.has_votes && c.mangler !== null"
                          x-text="'mangler ' + formatNum(c.mangler)"></span>
                  </div>
                </template>
              </div>
            </template>
          </div>
        </template>
      </div>
    </template>

    <!-- National view (no active storkreds) -->
    <template x-if="partyDetail && !activeStorkreds">
      <div>
        <template x-for="p in partyDetail" :key="p.id">
          <div class="party-detail-block">
            <div class="party-detail-name"
                 x-text="(p.letter || p.id) + ' — ' + p.name"></div>
            <div class="party-detail-meta"
                 x-text="formatNum(p.votes) + ' votes (' + p.pct + '%) · ' + p.seats_total + ' seats'">
            </div>
            <!-- Candidate breakdown -->
            <template x-if="!p.has_votes && p.candidates.length > 0">
              <div>
                <div class="cand-breakdown-prelim-note">Foreløbig rækkefølge — stemmetal tilgængeligt efter fintælling</div>
                <template x-for="(c, i) in p.candidates" :key="c.id">
                  <div class="cand-breakdown-row" :class="i < p.seats_total ? 'cand-in' : 'cand-out'">
                    <span class="cand-breakdown-name" x-text="(i + 1) + '. ' + c.name"></span>
                    <span class="cand-breakdown-kreds" x-text="c.opstillingskreds + ' · ' + c.storkreds"></span>
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
                    <div class="cand-breakdown-row" :class="c.elected ? 'cand-in' : 'cand-out'">
                      <span class="cand-breakdown-name" x-text="c.name"></span>
                      <span class="cand-breakdown-kreds" x-text="c.opstillingskreds"></span>
                      <span class="cand-breakdown-sk"
                            x-text="c.sk_seats > 0 ? '#' + c.sk_rank + ' i ' + c.storkreds + ' (' + c.sk_seats + ' mandater)' : '#' + c.sk_rank + ' i ' + c.storkreds">
                      </span>
                      <span class="cand-breakdown-votes" x-text="c.votes !== null ? formatNum(c.votes) : '—'"></span>
                    </div>
                  </div>
                </template>
              </div>
            </template>
            <template x-if="p.candidates.length === 0">
              <div class="detail-placeholder" style="padding:8px 0">Ingen kandidater</div>
            </template>
          </div>
        </template>
      </div>
    </template>
  </div>
</template>
```

- [ ] **Step 4: Commit**

```bash
git add valg/templates/index.html
git commit -m "feat: storkreds-grouped candidates column and elected/bubble detail panel"
```

---

## Task 4: CSS — storkreds header, active indicator, section labels

**Files:**
- Modify: `valg/static/app.css`

Read the existing CSS first to understand naming conventions and colour palette before adding. Then append the following at the end of `app.css`:

- [ ] **Step 1: Add styles**

Append to `valg/static/app.css`:

```css
/* ── Storkreds group header (candidates column) ────────────────────────────── */
.sk-group-header {
  padding: 5px 10px;
  font-size: 0.75em;
  font-weight: 600;
  color: #8b949e;
  cursor: pointer;
  user-select: none;
  border-bottom: 1px solid #21262d;
  letter-spacing: 0.04em;
  text-transform: uppercase;
}

.sk-group-header:hover {
  background: #161b22;
  color: #c9d1d9;
}

.sk-group-header--active {
  color: #58a6ff;
  background: #0d1117;
}

.sk-active-indicator {
  color: #58a6ff;
}

/* ── Storkreds detail panel heading ────────────────────────────────────────── */
.sk-detail-heading {
  font-size: 0.85em;
  font-weight: 600;
  color: #58a6ff;
  padding: 8px 12px 4px;
  border-bottom: 1px solid #21262d;
  margin-bottom: 4px;
  letter-spacing: 0.03em;
  text-transform: uppercase;
}

/* ── Elected / Ikke valgt section labels ───────────────────────────────────── */
.sk-section-label {
  font-size: 0.7em;
  font-weight: 600;
  color: #8b949e;
  padding: 6px 12px 2px;
  letter-spacing: 0.05em;
  text-transform: uppercase;
}

/* ── Mangler annotation ────────────────────────────────────────────────────── */
.cand-breakdown-mangler {
  font-size: 0.8em;
  color: #f85149;
  margin-left: 6px;
  white-space: nowrap;
}
```

- [ ] **Step 2: Smoke-test in browser**

Start the server with demo data and verify:

```bash
python -m valg.server --demo --port 5000
```

1. Select a party — candidates column should show storkreds group headers
2. Click a storkreds header — other groups collapse, `▸` appears, header turns blue
3. Click the active header again — all groups expand
4. Detail panel when storkreds active — shows "Storkreds X" heading, party sub-blocks with "Valgte" / "Ikke valgt" sections
5. Deselect all parties — `activeStorkreds` clears (re-selecting shows all groups expanded)
6. Pre-fintælling scenario (default demo) — no vote numbers, no "mangler" annotations

- [ ] **Step 3: Run full test suite**

```bash
pytest -v
```

Expected: all green

- [ ] **Step 4: Commit**

```bash
git add valg/static/app.css
git commit -m "feat: CSS for storkreds group headers and elected/bubble section labels"
```
