# Activity Feed + Place Drill-down

**Date:** 2026-03-21
**Status:** Approved

## Problem

The dashboard shows aggregate vote counts and seat projections but gives no feel for *where* data is coming from. There is no way to see which polling places have reported in, or to inspect how a specific place contributed to party and candidate counts.

## Goals

- Constant visibility into which places have reported, in real time
- Click any place to see its full vote breakdown (parties + candidates)
- Resizable UI to suit election-night monitoring workflows

## Design

### Bottom Feed Panel

A permanent panel anchored to the bottom of the dashboard. It replaces the existing thin event strip.

**Layout:**
- Header row: label "Indberetninger" + count badge (e.g. "847 / 1291 steder")
- Scrollable list below: one row per reported polling place, newest first
- Each row: place name (afstemningsomraade), count type (`foreløbig` / `fintælling`), timestamp

**Resizing:**
- Drag the top edge to resize height
- Minimum: ~2 rows visible
- Collapses to header-only if dragged fully down
- Resize state saved to `localStorage`

**Auto-scroll:**
- When a new place reports in, the list jumps to the top (row 0)
- Exception: if the user has a place selected (highlighted row), the list stays at its current scroll position so the selection isn't displaced

### Place Drill-down (Sted Tab)

Clicking a place row in the feed opens a **"Sted" tab** in the right detail panel, alongside the existing "Partier" and "Kandidat" tabs.

**Tab contents:**
- Header: place name, opstillingskreds, count type, timestamp
- **Party votes table:** letter, full name, vote count, delta since previous snapshot (if available)
- **Candidate votes table:** candidate name, party letter, vote count — only shown when `fintælling` data exists for this place; otherwise a note: *"Kandidatstemmer ikke tilgængeligt ved foreløbig optælling"*

**Tab lifecycle:**
- Persists until the user explicitly clicks another place (which replaces it) or closes it
- Selecting a party or candidate in the left columns switches the active tab to Partier/Kandidat but does not remove the Sted tab — user can switch back

### Column Resizing

The three main columns (Partier, Kandidater, Detaljer) are resizable by dragging the dividers between them. Widths saved to `localStorage`.

## Data Sources

All data is already in the database:

| Need | Source |
|------|--------|
| Feed rows (place + timestamp) | `events` table, `event_type = 'district_reported'` |
| Party votes per place | `results` table, latest snapshot per `afstemningsomraade_id` |
| Candidate votes per place | `results` table, `candidate_id IS NOT NULL`, latest snapshot |
| Vote delta | Compare latest two snapshots per `afstemningsomraade_id` |

### New API Endpoints

- `GET /api/feed/places?limit=N&offset=M` — paginated list of reported places (name, count_type, occurred_at), newest first. Replaces the current `/api/feed`.
- `GET /api/place/<id>` — party votes + candidate votes for a single afstemningsomraade, latest snapshot only, with delta vs. previous snapshot.

The existing `/api/feed` endpoint can be kept for backward compatibility or deprecated — it is currently used only by the bottom strip.

## Frontend Changes

### `index.html` / `app.js`

- Replace bottom feed strip markup with resizable panel (CSS `resize` or JS drag handler on top border)
- Add `selectedPlaceId` to Alpine state
- Feed rows: click sets `selectedPlaceId`, triggers `GET /api/place/<id>`, opens Sted tab
- Sted tab: renders party table and (conditionally) candidate table from API response
- Auto-scroll: on feed data refresh, if `selectedPlaceId` is null, scroll feed to top; otherwise preserve scroll
- `localStorage` persistence for column widths and feed panel height

### `server.py`

- Add `/api/feed/places` endpoint (query against `events` table)
- Add `/api/place/<id>` endpoint (query against `results` table)

### `queries.py`

- `query_feed_places(conn, limit, offset)` — events WHERE event_type='district_reported', JOIN afstemningsomraader for name
- `query_place_detail(conn, place_id)` — latest snapshot party votes + optional candidate votes + previous snapshot for delta

## Out of Scope

- Filtering the feed by opstillingskreds or storkreds (future)
- Search/filter within the feed

## Future Idea

**Pivot into results mode:** clicking a place navigates the whole dashboard to focus on that district — highlights its opstillingskreds in the party column, filters candidates to that kreds, activates the Sted tab. A deeper drill-down mode for tracking a specific area through the night.
