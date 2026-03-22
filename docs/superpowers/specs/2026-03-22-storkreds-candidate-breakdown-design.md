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

2. **SQL change**: add `ok.storkreds_id` and `sk.name AS storkreds_name` to both the fintælling and preliminary candidate SELECT clauses, via `JOIN storkredse sk ON sk.id = ok.storkreds_id`. This gives each candidate row a `storkreds_id` for grouping and a `storkreds_name` for display.

3. **D'Hondt lookup dict**: build `sk_seats_for_party: dict[str, int]` mapping `sk_id → kredsmandat seats for this party` from the per-storkreds D'Hondt loop. This is separate from `seats_breakdown` (which does not store `sk_id`). The loop already runs over `storkreds_votes.items()`; extend it to also populate this dict.

4. **Rank computation**: after fetching candidates, group by `storkreds_id`, sort each group by `votes DESC` (fintælling) or `ballot_position ASC` (preliminary), assign 1-based ranks. Annotate each candidate dict with `sk_rank`, `sk_seats` (from `sk_seats_for_party`), and `elected`. All four new fields (`storkreds`, `sk_rank`, `sk_seats`, `elected`) are present in the returned dict for both fintælling and preliminary phases — the frontend decides what to display.

Existing fields (`cutoff_margin`, `seats_total`, `has_votes`, `candidates`) are unchanged. The national cutoff line and national seat count remain accurate.

**Tillægsmandater caveat**: `elected` and `sk_seats` are based on kredsmandat D'Hondt only. Parties winning tillægsmandater may elect additional candidates beyond `sk_seats` — this cannot be computed per-storkreds without the full allocation. `seats_total` (national, including tillægs) remains the accurate total.

### `valg/templates/index.html`

Two changes to the fintælling candidate list (`x-if="p.has_votes"`):

1. **Coloring (fintælling only)**: change `:class="i < p.seats_total ? 'cand-in' : 'cand-out'"` to `:class="c.elected ? 'cand-in' : 'cand-out'"` in the `x-if="p.has_votes"` block only. This colours each row by local kredsmandat election status.

   The visual consequence is intentional and is the point of the feature: candidates sorted by national personal votes will be interleaved green/grey — a Bornholm candidate with 891 votes appears green between Copenhagen candidates with 3,000+ votes who appear grey. This cross-storkreds contrast tells the story.

2. **Badge (fintælling only)**: add a storkreds badge to each candidate row in the fintælling list:
   - When `c.sk_seats > 0`: `#N i [Storkreds] (M mandater)` where N = `c.sk_rank`, M = `c.sk_seats`
   - When `c.sk_seats === 0`: `#N i [Storkreds]` (party wins no kredsmandat seat there)
   - Styled as a muted inline label distinct from the candidate name and vote count

3. **National cutoff line**: stays at `x-show="i === p.seats_total"` with label `Grænse · X stemmer`. Because coloring is now per-storkreds, some candidates above the line will be grey and some below will be green — this is correct and expected. The line shows the national boundary; the colours show local reality.

4. **Preliminary list** (`x-if="!p.has_votes"`): add the storkreds name to each row as informational text. Leave the existing `i < p.seats_total ? 'cand-in' : 'cand-out'` coloring unchanged — without vote data, the ballot-position ordering is the only signal available. Do not show `sk_rank`/`sk_seats` badge.

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

- **Cross-storkreds scenario**: party wins 2 seats in storkreds A and 0 seats in storkreds B. Candidate ranked #2 in A (fewer total votes) must have `elected=True`; candidate ranked #1 in B (more total votes) must have `elected=False`. This is the core scenario the feature is designed to surface.
- **Rank correctness**: two storkredse with multiple candidates each — verify `sk_rank` is 1-based and local to each storkreds, not global.
- **Zero-seat storkreds**: candidates in a storkreds where party wins 0 kredsmandater — `sk_seats=0`, `elected=False`.
- **Preliminary phase**: `elected=False` for all candidates; `sk_rank` based on `ballot_position` within storkreds; `sk_seats` still populated.
- **Existing fields unchanged**: `cutoff_margin`, `seats_total`, `has_votes`, `candidates` list order — all identical to current behaviour.
- No frontend tests — visual correctness verified manually.

---

## Out of Scope

- Tillægsmandat per-storkreds distribution (requires full national allocation not in scope)
- Changing the national cutoff line label or position
- Reordering candidates by storkreds (national vote sort preserved)
