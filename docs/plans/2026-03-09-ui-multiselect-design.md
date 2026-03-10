# Web UI — Multi-Select & Party Overview Design

**Date:** 2026-03-09
**Scope:** `valg/server.py`, `valg/queries.py`
**Status:** Approved

---

## Problem

The current web UI has free-text inputs for party letter, candidate name, and kreds name.
There is no way to select multiple entities, no data-driven dropdowns, and no party-level
candidate overview (who's elected, who's on the bubble, margins between adjacent candidates).

---

## Goals

1. Replace free-text inputs with data-driven checkboxes populated from the DB
2. Add a Party Overview view: ranked candidates, seat status, margins
3. Support multi-entity selection across all views (combined table, not side-by-side)
4. CSV export works for all views from client-side JSON serialisation

---

## API Endpoints

Two new endpoints added to `server.py`:

### `GET /api/options`

Called once on page load. Returns all parties, kredse, and candidates from the DB.

```json
{
  "parties":    [{"id": "A", "name": "Socialdemokratiet"}],
  "kredse":     [{"id": 1,   "name": "Østerbro"}],
  "candidates": [{"id": 42,  "name": "Mette Frederiksen", "party_id": "A"}]
}
```

Empty arrays if no data loaded yet.

### `POST /api/query`

Single query endpoint. Accepts command name and selected IDs.

```json
{ "cmd": "party_overview", "parties": ["A", "B"], "kredse": [], "candidates": [] }
```

Returns structured rows + column names:

```json
{ "columns": ["rank", "candidate", "party", "votes", "margin", "status"], "rows": [...] }
```

Empty selections are treated as "all" (unfiltered) for each panel.

The existing `/run` (plain text) and `/csv/<cmd>` endpoints are preserved but no longer
used by the UI. They may be removed in a follow-up cleanup.

---

## Frontend UI

The controls bar is replaced with three collapsible checkbox panels + view buttons.
Same dark monospace aesthetic (`#0d1117` background, `#c9d1d9` text, `#30363d` borders).

```
┌──────────────────────────────────────────────────────────────┐
│ [▼ Partier]  [▼ Kredse]  [▼ Kandidater]                      │
│  ☑ A – Soc.dem   ☑ B – ...   ☐ C – ...  (scrollable panel)  │
│                                                              │
│ [Status] [Flip] [Party Overview] [Kreds] [Feed] [Commentary] │
│ [Download CSV]                                               │
└──────────────────────────────────────────────────────────────┘
```

### Checkbox panels

- Populated from `/api/options` on page init; show `(loading...)` until ready
- Selecting a party in the Partier panel filters the Kandidater panel to only that party's candidates
- "Select all / none" toggle per panel
- Max-height scrollable list

### Output

- Rendered as a `<table>` built from JSON rows (replaces `<pre>` plain text output)
- CSV button serialises current JSON rows client-side (no extra server round-trip)

---

## Views & Multi-Select Behaviour

### Party Overview (new)

Query function: `query_party_overview(conn, party_ids)` in `queries.py`

Columns: `rank`, `candidate`, `party`, `votes`, `margin_to_above`, `status`

- `votes` — fintælling if available, falls back to preliminary
- `margin_to_above` — gap to the candidate ranked above; blank for rank 1
- `status` — `elected`, `bubble` (within one seat margin), or `not elected`; derived from projected seats per party
- Rows sorted by votes descending across all selected parties combined
- If no fintælling data: candidate rows omitted, party-level summary shown with a `(fintælling pending)` note

### Status

Columns: `party`, `votes`, `pct`, `seats`

If parties selected: filter to those parties. Otherwise: all parties.

### Flip

Columns: `party`, `seats`, `votes_to_gain`, `votes_to_lose`

If parties selected: filter to those parties. Otherwise: top 10 closest nationally.

### Kreds

Columns: `candidate`, `party`, `votes`, `margin_to_above`

If kredse selected: filter to those opstillingskredse.
If candidates selected: spotlight those candidates within the kreds result.

### Feed / Commentary

Unaffected by checkbox selections.

---

## Files Changed

| File | Change |
|---|---|
| `valg/server.py` | Add `/api/options` and `/api/query` endpoints; replace embedded HTML |
| `valg/queries.py` | Add `query_party_overview`; extend existing query functions to accept filter lists |

No CLI changes required unless the new query functions are useful enough to expose as
`valg party-overview A B` — deferred until there is a clear use case.

---

## Out of Scope

- TUI / terminal multi-select
- Side-by-side panel comparison
- Persistent selection state across page reloads (localStorage)
