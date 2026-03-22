# Per-Storkreds Candidate Breakdown Design

**Date:** 2026-03-22
**Scope:** Show each candidate's storkreds context in the party detail panel, so it is visible that a candidate with fewer personal votes can be elected because they run in a different district.

---

## Problem

The current candidate breakdown sorts all candidates for a party by personal votes nationally and draws a single cutoff line at `seats_total`. This hides the key mechanic of the Danish Folketing election: seats are allocated per storkreds via D'Hondt, so a candidate with 891 votes in Bornholms Storkreds can be elected while a candidate with 3,888 votes in Københavns Storkreds is not, because the Copenhagen party candidates fill all their local seats ahead of them.

---

## Design

### `valg/queries.py` — `query_api_party_detail`

Two additions per candidate in the returned list:

1. **Storkreds context fields** added to each candidate dict:
   - `storkreds`: storkreds name (string)
   - `sk_rank`: the candidate's rank by personal votes within their party in their storkreds (1 = most votes), integer. In preliminary phase (no votes): rank by `ballot_position` instead.
   - `sk_seats`: kredsmandat seats the party wins in that storkreds, from D'Hondt. Integer, 0 if the party wins no seats there.
   - `elected`: bool — `True` if `sk_rank <= sk_seats`. Only meaningful when `has_votes` is `True`; set to `False` in preliminary phase.

2. **SQL change**: the candidate query joins `candidates → opstillingskredse → storkredse` to fetch `storkreds_id` and `storkreds name`. The D'Hondt per-storkreds result (already computed for `seats_breakdown`) is reused to look up `sk_seats` per candidate.

3. **Rank computation**: after fetching candidates, group by `storkreds_id`, sort each group by `votes DESC` (fintælling) or `ballot_position ASC` (preliminary), assign 1-based ranks. Then annotate each candidate dict.

Existing fields (`cutoff_margin`, `seats_total`, `has_votes`, `candidates`) are unchanged. The national cutoff line and national seat count remain accurate.

**Tillægsmandater caveat**: `elected` and `sk_seats` are based on kredsmandat D'Hondt only. Parties winning tillægsmandater may elect additional candidates beyond `sk_seats` — this cannot be computed per-storkreds without the full allocation. `seats_total` (national, including tillægs) remains the accurate total.

### `valg/templates/index.html`

Two changes to the fintælling candidate list (`x-if="p.has_votes"`):

1. **Coloring**: change `:class="i < p.seats_total ? 'cand-in' : 'cand-out'"` to `:class="c.elected ? 'cand-in' : 'cand-out'"`. This colours each row by local election status rather than national rank.

2. **Badge**: add a storkreds badge to each candidate row, shown only when `c.sk_seats > 0`:
   - Format: `#N i [Storkreds] (M mandater)` where N = `c.sk_rank`, M = `c.sk_seats`
   - If `c.sk_seats === 0`: show only `#N i [Storkreds]` (party wins no kredsmandat there)
   - Styled as a muted inline label (`.cand-breakdown-kreds` class or similar), distinct from the candidate name and vote count

The national cutoff line stays in place at position `seats_total` in the nationally-sorted list. Its label remains `Grænse · X stemmer`.

The preliminary list (`x-if="!p.has_votes"`) gets the storkreds name added to each row (informational only) but no `elected` colouring and no `sk_rank`/`sk_seats` badge — vote outcomes are unknown.

---

## Data Flow

```
query_api_party_detail(conn, party_ids)
  → get_seat_data(conn)
      → national_votes, storkreds_votes, kredsmandater
  → allocate_seats_total(...)       # national seats_total per party (unchanged)
  → dhondt(sk_votes, n) per sk     # kredsmandat seats per party per storkreds
  → SQL: candidates JOIN opstillingskredse JOIN storkredse
  → group candidates by storkreds_id
  → rank within each group
  → annotate each candidate: storkreds, sk_rank, sk_seats, elected
  → return list[dict] with enriched candidates
```

---

## Testing

- Unit test: `query_api_party_detail` with synthetic data — party wins seats in two storkredse; verify `sk_rank`, `sk_seats`, `elected` are correct for candidates in each storkreds.
- Test edge case: party wins 0 seats in a storkreds — candidates there have `sk_seats=0`, `elected=False`.
- Test preliminary phase: `elected=False` for all, `sk_rank` based on ballot_position.
- Existing `query_api_party_detail` tests continue to pass (existing fields unchanged).
- No frontend tests — visual correctness verified manually.

---

## Out of Scope

- Tillægsmandat per-storkreds distribution (requires full national allocation not in scope)
- Changing the national cutoff line label or position
- Reordering candidates by storkreds (national vote sort preserved)
