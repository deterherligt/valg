# Storkreds Filter & Elected/Bubble View

**Date:** 2026-03-23
**Status:** Approved

## Summary

Add storkreds-based filtering to the candidates column and restructure the party detail panel to show elected candidates above the line and bubble candidates below, grouped per storkreds.

## Candidates Column

Candidates are always rendered in storkreds groups (replacing the current party-grouped layout in both the active-storkreds and no-storkreds cases). Each storkreds group has a clickable header row showing `Storkreds navn`. Within each storkreds group, candidates from different parties appear as a flat list (no party sub-headers in the candidates column).

- When no storkreds is active: all groups are expanded
- Clicking a header sets `activeStorkreds = { id: candidate.storkreds_id, name: candidate.storkreds }` — other groups collapse (header row remains visible, content hidden), active group expands
- Clicking the active header again clears `activeStorkreds = null` (all groups expand)
- A `▸` indicator on the active header; collapsed inactive headers show no indicator
- Inactive group headers are always visible so the user can switch storkreds without first clearing the filter

**Empty state (candidates column):** shown when all selected parties have no candidates in the active storkreds — "Ingen kandidater i denne storkreds".

**Pre-fintælling:** each candidate row shows name + opstillingskreds + ballot position — no vote counts.

### Backend change

`/api/candidates` response gains two new fields per candidate:
- `storkreds` — storkreds name (string)
- `storkreds_id` — storkreds TEXT id (SQLite schema: `storkredse.id TEXT` — string equality is safe)

These come from adding `JOIN storkredse sk ON sk.id = ok.storkreds_id` to `query_api_candidates`.

### Frontend change

`candidatesByParty` computed getter is **replaced** by `candidatesByStorkreds`, which groups candidates by storkreds. The storkreds groups are always used — no fallback to party grouping.

## Party Detail Panel

The party detail data (`/api/party-detail`) is fetched for all storkredse as before. When `activeStorkreds` is set, the frontend filters the already-fetched candidate list client-side to only include candidates where `candidate.storkreds === activeStorkreds.name`, then renders the elected/bubble layout. When `activeStorkreds` is null, the panel is unchanged (national candidate list).

### Layout

One storkreds heading at the top (`Storkreds navn`); each selected party gets its own sub-block.

```
Storkreds København
────────────────────────────────────────
A — Socialdemokratiet — 2 mandater
─── Valgte ──────────────────────────
1. Anders Nielsen         12.341
2. Mette Olsen             9.872
─── Ikke valgt ──────────────────────
3. Lars Pedersen           7.100   mangler 2.773
4. Sara Jensen             4.200   mangler 5.673
```

**Separator** sits between `sk_rank === sk_seats` and `sk_rank === sk_seats + 1`. "Mangler X" is only shown for non-elected (bubble) candidates — not for elected candidates.

**`sk_seats` invariant:** all candidates in a given party × storkreds group share the same `sk_seats` value (it reflects D'Hondt-allocated seats for that party in that storkreds). Use the value from the first candidate in the group for the sub-block header.

**`sk_seats === 0`:** no separator; all candidates appear under "Ikke valgt" with no margin numbers (party has no seats in this storkreds).

**Mangler X** (bubble section only) = `last_elected_votes - candidate_votes + 1`, where `last_elected_votes` = votes of candidate at `sk_rank === sk_seats`. A tied candidate shows "mangler 1" — intentional (needs strictly more votes to overtake).

**Ordering:** `sk_rank` ascending in both elected and bubble sections.

**Pre-fintælling (`has_votes === false`):**
- `sk_seats` is still valid (computed from preliminary party votes via D'Hondt)
- `sk_rank` is by ballot position order (backend computes this consistently)
- Separator is shown as a projection: "Valgte" = top N by ballot position; "Ikke valgt" = rest
- No vote numbers, no margin numbers

**Empty state per party:** if a selected party has no candidates in the active storkreds, show "Ingen kandidater i denne storkreds" for that party's sub-block.

## State

```js
activeStorkreds: null,  // { id: string, name: string } | null
```

- Set by clicking a storkreds header (constructs `{ id: storkreds_id, name: storkreds }` from candidate data)
- Cleared by clicking the active header again
- Cleared when **all** parties are deselected
- Persists on partial deselect (removing one of multiple selected parties)
- After full deselect clears `activeStorkreds`, re-selecting a party starts with `activeStorkreds === null`; user must click a storkreds header again to re-activate filtering

## Out of Scope

- Feed panel filtering by storkreds
- Per-storkreds tillægsmandater breakdown
- URL persistence of active storkreds
