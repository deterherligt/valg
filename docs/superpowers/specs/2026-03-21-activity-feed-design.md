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
- Header row: label "Indberetninger" + count badge using `districts_reported` / `districts_total` from the existing `/api/status` response (no new endpoint needed)
- Scrollable list below: one row per reported polling place, newest first
- Each row: place name (from `afstemningsomraader.name`), count type (display: `foreløbig` / `fintælling`), timestamp

**Resizing:**
- Drag the top edge to resize height; JS drag handler on the top border
- Minimum: ~2 rows visible
- Collapses to header-only if dragged fully down
- Resize state saved to `localStorage`

**Auto-scroll:**
- The feed is re-fetched from the top (page 1, no `before_id`) on every `just_synced` event — same trigger as parties, candidates, and status
- On re-fetch, scroll to row 0 if `selectedPlaceId` is null; preserve scroll position if a place is selected

### Place Drill-down (Sted Tab)

Clicking a place row opens a **"Sted" tab** in the right detail panel. The tab bar normally shows "Partier" and "Kandidat"; "Sted" appears dynamically when a place is first selected and is absent until then.

**Tab contents:**
- Header: place name, opstillingskreds name, count type (`foreløbig`/`fintælling`), timestamp
- **Party votes table:** party letter, full name, vote count, delta vs. previous snapshot. Delta is `—` if this is the first snapshot for the place. Delta compares the two most recent distinct `snapshot_at` values for the place regardless of `count_type` — a final count succeeding a preliminary will show the full delta between them, which is intentional.
- **Candidate votes table:** rendered from `results WHERE candidate_id IS NOT NULL` for the latest snapshot. Because candidate rows only exist for `count_type = 'final'`, this query naturally returns empty during foreløbig. Show the note *"Kandidatstemmer ikke tilgængeligt ved foreløbig optælling"* when the result is empty.

**"Latest snapshot" for a place:** rows with the maximum `snapshot_at` for the given `afstemningsomraade_id`. If `final` and `preliminary` rows share the same `snapshot_at`, prefer `final` — use `ORDER BY count_type ASC` (`'f' < 'p'`, so `'final'` sorts first ascending). The header `count_type` reflects the actual type of the returned rows.

**Tab lifecycle:**
- Appears on first click; the tab label stays "Sted" and its contents are replaced when user clicks a different place
- Navigating to Partier/Kandidat tab does not remove Sted — user can switch back
- Removed on page refresh

### Column Resizing

The three main columns use `.columns { display: flex }` in `app.css`. Add invisible drag-handle `<div>` elements between each column pair. On `mousedown`, a `mousemove` listener adjusts the preceding column's `flex-basis` (in px) and updates Alpine state. On `mouseup`, persist widths to `localStorage` and restore on load. Min width per column: 120px.

## Data Sources

All data is in the existing database:

| Need | Source |
|------|--------|
| Feed rows (place + count_type + timestamp) | `events` WHERE `event_type = 'district_reported'`; `subject` = `afstemningsomraade_id` (JOIN for name); `count_type` parsed from `description` (`"preliminary results"` / `"final results"`) |
| Party votes per place | `results`, rows at max `snapshot_at` per `afstemningsomraade_id` |
| Candidate votes per place | `results`, `candidate_id IS NOT NULL`, max `snapshot_at` per place |
| Vote delta | Two most recent distinct `snapshot_at` timestamps for the place; within each timestamp, prefer `final` rows over `preliminary` (`ORDER BY count_type ASC`, `'final' < 'preliminary'`). `null` delta if only one distinct `snapshot_at` exists. |
| Count badge totals | `districts_reported` / `districts_total` already in `/api/status` response |

### New API Endpoints

- `GET /api/feed/places?before_id=<event_id>&limit=N` — cursor-paginated, newest first. Omit `before_id` for the first page; pass the smallest `event_id` seen so far to fetch the next page of older entries. The query filter is `id < before_id`. Default `limit=50`. The UI exposes a "load more" button at the bottom of the feed to trigger subsequent pages; accumulated items from older pages persist until the next `just_synced` re-fetch resets to page 1.
- `GET /api/place/<id>` — party votes + candidate votes for one afstemningsomraade, latest snapshot, with delta vs. previous snapshot.

The existing `/api/feed` endpoint is removed. Update `valg/static/app.js` (remove the `fetch('/api/feed')` call) and `tests/test_server.py` (replace the three `/api/feed` tests with new tests for the endpoints below).

### Test coverage required

- `GET /api/feed/places` with no data → empty list
- `GET /api/feed/places` with data → correct name, count_type, timestamp; newest first
- `GET /api/feed/places` cursor pagination: `before_id` returns older entries only
- `GET /api/place/<id>` with one snapshot → party votes present, delta is null
- `GET /api/place/<id>` with two snapshots → delta computed correctly
- `GET /api/place/<id>` with no final count → candidates empty
- `GET /api/place/<id>` with final count → candidates present

## Frontend Changes

### `index.html` / `app.js`

- Replace bottom feed strip markup with resizable panel
- Add `selectedPlaceId`, `placeDetail`, `feedItems` to Alpine state
- Re-fetch `feedItems` from `/api/feed/places` (page 1, no `before_id`) on `just_synced`; this replaces `feedItems` entirely — accumulated older pages are discarded on each sync. Remove existing `fetch('/api/feed')` call.
- "Load more" button at bottom of feed: appends the next page using `before_id = min(feedItems.map(x => x.event_id))`
- Feed rows: click sets `selectedPlaceId`, fetches `/api/place/<id>`, sets `placeDetail`, activates Sted tab
- Sted tab: renders party table + candidate table (or empty-candidate note) from `placeDetail`
- Auto-scroll to top on feed re-fetch when no place is selected
- `localStorage` persistence for column widths and feed panel height

### `server.py`

- Add `/api/feed/places` endpoint
- Add `/api/place/<id>` endpoint
- Remove `/api/feed` endpoint

### `queries.py`

- `query_feed_places(conn, before_id, limit)` — SELECT from `events` JOIN `afstemningsomraader` ON `afstemningsomraader.id = CAST(events.subject AS INTEGER)`, WHERE `event_type = 'district_reported'` AND (`before_id` is None OR `id < before_id`), parse `count_type` from `description`, ORDER BY `id` DESC
- `query_place_detail(conn, place_id)` — party votes at max `snapshot_at`, candidate votes at max `snapshot_at`, second-most-recent `snapshot_at` party votes for delta; within each `snapshot_at` group prefer `final` over `preliminary` using `ORDER BY count_type ASC`

### `models.py`

- Add index: `CREATE INDEX IF NOT EXISTS idx_events_type_id ON events(event_type, id)` to support efficient cursor-paginated feed queries

## Out of Scope

- Filtering the feed by opstillingskreds or storkreds (future)
- Search/filter within the feed

## Future Idea

**Pivot into results mode:** clicking a place navigates the whole dashboard to focus on that district — highlights its opstillingskreds in the party column, filters candidates to that kreds, activates the Sted tab. A deeper drill-down mode for tracking a specific area through the night.
