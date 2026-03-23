# Storkreds Filter & Elected/Bubble View

**Date:** 2026-03-23
**Status:** Approved

## Summary

Add storkreds-based filtering to the candidates column and restructure the party detail panel to show elected candidates above the line and bubble candidates below, grouped per storkreds.

## Candidates Column

Candidates are always rendered in storkreds groups. Each group has a clickable header showing `Storkreds navn (N kredsmandater)`.

- Clicking a header sets it as the active storkreds filter (`activeStorkreds` in Alpine state)
- Other groups collapse, leaving only that storkreds's candidates visible
- Clicking the active header again clears the filter (shows all groups)
- A `▸` indicator on the active header makes the filter state visible

### Backend change

`/api/candidates` response gains two new fields per candidate:
- `storkreds` — storkreds name (string)
- `storkreds_id` — storkreds id (string)

These come from the existing JOIN chain `candidates → opstillingskredse → storkredse` in `query_api_candidates`.

### Frontend change

`candidatesByParty` computed getter is replaced (or supplemented) by `candidatesByStorkreds` which groups first by storkreds, then by party within each storkreds group. When `activeStorkreds` is set, only that group is rendered.

## Party Detail Panel

When `activeStorkreds` is set, the detail panel switches from the national candidate list to a per-storkreds elected/bubble layout. When no storkreds is active, the panel is unchanged.

### Layout (per party per storkreds)

```
Storkreds København — 2 mandater
─── Valgte ───────────────────────
1. Anders Nielsen    A    12.341
2. Mette Olsen       A     9.872
─── Ikke valgt ───────────────────
3. Lars Pedersen     A     7.100   mangler 2.773
4. Sara Jensen       A     4.200   mangler 5.673
```

- **Separator** sits between `sk_rank === sk_seats` and `sk_rank === sk_seats + 1`
- **Mangler X** = `last_elected_votes - candidate_votes + 1`, computed frontend-side
- **Pre-fintælling**: bubble section shows ballot position order with no vote/margin numbers (consistent with existing pre-fintælling behaviour — `has_votes` flag already on each party detail response)
- **Multiple parties selected**: each party renders its own storkreds block, stacked as now

### Data

No new API endpoint or query change needed. `query_api_party_detail` already returns `storkreds`, `sk_rank`, `sk_seats`, `elected`, and `votes` per candidate. Vote margin is a pure frontend calculation.

## State

One new Alpine state variable:

```js
activeStorkreds: null,  // { id, name } | null
```

Set by clicking a storkreds header in the candidates column. Cleared by clicking again or by deselecting all parties.

## Out of Scope

- Feed panel filtering by storkreds
- Per-storkreds tillægsmandater breakdown
- URL persistence of active storkreds
