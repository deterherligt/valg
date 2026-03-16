# Dashboard Redesign — Design Spec

**Date:** 2026-03-15
**Status:** Approved

## Overview

Replace the current text-output single-panel UI with a three-column interactive dashboard. Users can select multiple parties, browse their candidates, and drill down into per-district vote counts — all on one page with a persistent live feed strip.

---

## Layout

```
┌─────────────────────────────────────────────────────────────────┐
│ valg                          Synced 21:14:32 · 847/1203 rptd  │
├──────────────┬───────────────┬────────────────────────────────  │
│   PARTIES    │  CANDIDATES   │  RIGHT PANEL                     │
│              │               │  (party-detail or cand-detail)   │
│  [x] A       │  [x] Mette F  │                                  │
│  [ ] V       │  [ ] Jakob E  │  (storkreds breakdown OR         │
│  [x] F       │  ─── SF ───   │   candidate district votes)      │
│  ...         │  [ ] Pia O.D. │                                  │
│              │  ...          │                                  │
├──────────────┴───────────────┴────────────────────────────────  │
│ FEED  21:14 · A +1,240 · Østerbro · 21:13 · F +892 · Frbg …   │
└─────────────────────────────────────────────────────────────────┘
```

### Party Column

- Lists all parties sorted by seats descending
- Each row: checkbox + party letter + name + votes + seats + flip margins
- Flip margins: `+12,400 to gain` (green) · `−15,200 to lose` (red)
- Multi-select: checking a party adds it to the active selection and populates the candidate column
- Selected parties highlighted with left border accent
- If the parties table is empty (no sync yet): column shows "Waiting for data..."

### Candidate Column

- Header shows selected party letters: "Candidates — A, F"
- Grouped by party with a party label separator
- Each row: checkbox + candidate name + opstillingskreds + ballot position
- Multi-select: candidates can be selected independently of each other
- Clicking a candidate (not just checking) focuses it and loads the right panel drilldown
- Vote counts shown on rows only during fintælling (otherwise omitted)

### Right Panel

Two modes, toggled by whether a candidate is focused:

**Party-detail mode** (no candidate focused):
- Shows expanded stats for all selected parties
- Per party: vote %, projected seats, seat breakdown by storkreds (table)
- Flip margins live on the party column rows only — not repeated here
- If no parties selected: "Select a party to see details"

**Candidate-detail mode** (candidate focused):
- Header: candidate name + party letter
- Table: afstemningsomraade name | votes — sorted by votes descending; unreported polling districts shown as "—". Rows are the afstemningsomraader within the candidate's own opstillingskreds.
- "X of Y polling districts reported" count (where Y = afstemningsomraader where `opstillingskreds_id = candidate's opstillingskreds_id`)
- Candidate feed below table: `+320 · Østerbro AO1 · 21:12` (newest first)
- When `available: false`: shows "Candidate votes available after fintælling begins"; `by_district` and feed are not rendered

### Feed Strip

- Persistent horizontal strip pinned to bottom of page
- Scrolls horizontally if overflow
- Format: `HH:MM · Party +N votes · District`
- Shows last 50 events, newest left
- Polled every 10s
- Source: `events.description` column (written by processor plugins)

### Header

- Left: "valg" logotype
- Right: "Synced HH:MM:SS · X/Y districts reported"
- `X/Y` = districts reported count from `/api/status`
- Updates on each poll cycle

---

## Technical Design

### File Structure

Current embedded HTML in `server.py` is replaced with proper Flask static/template serving:

```
valg/
  static/
    app.js       — Alpine.js component, all fetch + poll logic
    app.css      — three-column layout, dark theme
  templates/
    index.html   — Alpine-powered HTML, loads app.js + app.css
  server.py      — adds /api/* routes; existing /run /csv/* /sync-status stay
```

### Frontend

**Alpine.js** loaded from CDN (no build step). Single `x-data` component on `<body>`:

```js
{
  // Selection state (keyed by parties.id — opaque DB identifier)
  selectedPartyIds: [],      // array of parties.id values
  selectedCandidateIds: [],  // array of candidates.id values
  focusedCandidateId: null,  // candidates.id of drilldown target

  // Data
  parties: [],               // [{id, letter, name, votes, seats, pct, gain, lose}]
  candidates: [],            // [{id, name, party_id, party_letter, opstillingskreds, ballot_position}]
  partyDetail: null,         // [{id, letter, name, pct, seats_total, seats_by_storkreds}]
  candidateDetail: null,     // {name, party_letter, available, total_votes,
                             //  polling_districts_reported, polling_districts_total,
                             //  by_district: [{name, votes}]}
                             //  — when available: false, only name/party_letter/available present
  candidateFeed: [],         // [{occurred_at, district, delta}]
  feed: [],                  // [{occurred_at, description}]

  // Meta
  lastSynced: null,
  districtsReported: null,
  districtsTotal: null,
}
```

**Polling (every 10s):**
- Always: `/api/parties`, `/api/feed`, `/api/status`
- When parties selected: `/api/party-detail?party_ids=id1,id2`
- When candidate focused: `/api/candidate/<id>`, `/api/candidate-feed/<id>`
- On `just_synced=true` from `/api/status`: immediately re-fetch all active endpoints

**Known limitation:** `just_synced` is a one-shot flag reset on first read. Multiple open browser tabs will race — only the first tab to poll will see `just_synced=true`. Acceptable for v1.

**Interactions:**
- Checking a party → toggles `selectedPartyIds`, re-fetches candidates + party-detail
- Checking a candidate → toggles `selectedCandidateIds` (multi-select, no drilldown)
- Clicking a candidate row → sets `focusedCandidateId`, fetches candidate-detail + candidate-feed
- Clicking same candidate again → clears focus, returns to party-detail mode

### New API Routes

All return JSON. Existing routes (`/run`, `/csv/*`, `/sync-status`) unchanged.

#### `GET /api/status`

Returns sync metadata including district counts. Supersedes `/sync-status` for the new UI (old route kept for backwards compat).

```json
{
  "last_sync": "2024-11-05T21:14:32Z",
  "just_synced": false,
  "districts_reported": 847,
  "districts_total": 1203
}
```

`districts_reported` = `SELECT COUNT(DISTINCT opstillingskreds_id) FROM party_votes` — no snapshot filter, because different opstillingskredse report at different snapshot times and a per-snapshot filter would undercount. `districts_total` = total count of rows in `opstillingskredse`.

#### `GET /api/parties`

Returns all parties with latest snapshot votes, projected seats, and flip margins.

```json
[
  {
    "id": "Parti_A",
    "letter": "A",
    "name": "Socialdemokratiet",
    "votes": 482140,
    "seats": 48,
    "pct": 27.4,
    "gain": 12400,
    "lose": 15200
  }
]
```

Implementation: move `_get_seat_data()` from `cli.py` into `queries.py` (which already imports it from `cli.py` — this resolves that circular coupling). Update `cli.py` to import from `queries.py`. `server.py` then also imports from `queries.py`. Use `allocate_seats_total()` + `votes_to_gain_seat` / `votes_to_lose_seat` from `calculator.py`. `parties.letter` may be null for unknown parties — such rows are included with `letter: null`; the UI renders `id` as fallback.

#### `GET /api/candidates?party_ids=Parti_A,Parti_F`

Returns candidates for the given party IDs, grouped by party.

```json
[
  {
    "id": "cand_42",
    "name": "Mette Frederiksen",
    "party_id": "Parti_A",
    "party_letter": "A",
    "opstillingskreds": "Østerbro",
    "ballot_position": 1
  }
]
```

Query: `candidates JOIN parties ON candidates.party_id = parties.id` filtered by `party_id IN (...)`, ordered by `party_id, ballot_position`.

#### `GET /api/party-detail?party_ids=Parti_A,Parti_F`

Returns expanded stats for selected parties including seat breakdown by storkreds.

```json
[
  {
    "id": "Parti_A",
    "letter": "A",
    "name": "Socialdemokratiet",
    "votes": 482140,
    "pct": 27.4,
    "seats_total": 48,
    "seats_by_storkreds": [
      {"name": "Københavns Storkreds", "seats": 12},
      {"name": "Sjællands Storkreds", "seats": 8}
    ]
  }
]
```

#### `GET /api/candidate/<id>`

Returns per-opstillingskreds vote breakdown for a candidate. Votes are aggregated from `afstemningsomraader` up to `opstillingskreds` level.

**When fintælling available (`available: true`):**
```json
{
  "name": "Mette Frederiksen",
  "party_letter": "A",
  "available": true,
  "total_votes": 15860,
  "polling_districts_reported": 8,
  "polling_districts_total": 12,
  "by_district": [
    {"name": "Østerbro AO1", "votes": 5120},
    {"name": "Østerbro AO2", "votes": 3840},
    {"name": "Østerbro AO3", "votes": null}
  ]
}
```

`by_district` rows are the `afstemningsomraader` within the candidate's own `opstillingskreds`. A row with `votes: null` means no `results` row matched that district (not yet reported — show "—"). A row with `votes: 0` means the candidate received zero votes in that district (reported, show "0"). `polling_districts_total` = count of afstemningsomraader where `opstillingskreds_id = candidate.opstillingskreds_id`. `polling_districts_reported` = count of `by_district` rows where `votes IS NOT NULL`.

**When fintælling not yet started (`available: false`):**
```json
{
  "name": "Mette Frederiksen",
  "party_letter": "A",
  "available": false
}
```

`available: false` when no rows exist in `results` for this `candidate_id`. `votes: null` for opstillingskredse with no reported afstemningsomraader yet.

Query (when available): Drive from `afstemningsomraader WHERE opstillingskreds_id = candidate.opstillingskreds_id` LEFT JOIN `results ON results.afstemningsomraade_id = afstemningsomraader.id AND results.candidate_id = ? AND results.snapshot_at = (SELECT MAX(snapshot_at) FROM results WHERE candidate_id = ?)`. This ensures all polling districts in the candidate's opstillingskreds appear in the result, with `votes = null` for those not yet reported. Also JOIN `candidates ON candidates.id = ?` and `parties ON candidates.party_id = parties.id` to populate name and party_letter.

#### `GET /api/feed?limit=50`

Returns recent events from the `events` table. The `description` column is written by processor plugins and contains a human-readable summary.

```json
[
  {"occurred_at": "2024-11-05T21:14:00Z", "description": "A +1,240 · Østerbro"}
]
```

Query: `SELECT occurred_at, description FROM events ORDER BY occurred_at DESC LIMIT ?`

#### `GET /api/candidate-feed/<id>?limit=20`

Returns vote delta events for a specific candidate, computed by diffing consecutive snapshots in `results`, partitioned by `afstemningsomraade_id`.

```json
[
  {"occurred_at": "2024-11-05T21:12:00Z", "district": "Østerbro", "delta": 320}
]
```

Query pattern: for each `(afstemningsomraade_id, snapshot_at)` pair where `candidate_id = ?`, compute `votes - LAG(votes) OVER (PARTITION BY afstemningsomraade_id ORDER BY snapshot_at)`. Return rows where delta > 0, ordered by `occurred_at DESC`, joined to `afstemningsomraader.name` for the district label.

---

## Graceful Degradation

| Situation | Behaviour |
|---|---|
| DB empty (no sync yet) | Party column: "Waiting for data..."; all other columns empty |
| No parties selected | Candidate column empty; right panel: "Select a party to see details" |
| Election night (no fintælling) | Candidate rows show no vote counts; drilldown shows "Candidate votes available after fintælling begins" |
| Opstillingskreds not yet reported | Shows "—" in candidate district table |
| No events yet | Feed strip: "No events yet" |
| `parties.letter` is null | UI renders `party_id` as fallback identifier |
| Sync in progress | Header pulses; data refreshes when `just_synced` fires |

---

## Out of Scope

- Party colors / logos
- Candidate photos
- Seat visualisation (bar chart, parliament diagram)
- Bloc groupings (red/blue bloc totals)
- The existing `/run` text-output interface (kept as-is, not removed)
