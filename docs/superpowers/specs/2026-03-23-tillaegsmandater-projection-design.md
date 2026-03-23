# Tillægsmandater Projection Design

## Problem

The valg dashboard currently approximates tillægsmandater by subtracting kredsmandater from a national modified Saint-Lague allocation of all 175 seats. This is inaccurate because:

1. Proper tillaegsmandat allocation uses each party's kredsmandater as a baseline divisor, not a flat first-divisor of 1.4
2. Storkreds assignment of tillaeg seats is not computed at all
3. The FV2022 scenario data is missing ~48% of votes due to two bugs in the build script
4. There is no projection layer for partial election night data

This spec covers three workstreams in order: fix data, implement proper math, add projection.

## Workstream 1: Fix FV2022 Scenario Data

### Bug 1: Only Partiliste votes counted

`scripts/build_fv2022_scenario.py` filters to `row["Navn"] == "Partiliste"`, discarding all personal votes for candidates. In Danish elections, a party's total votes = Partiliste + personal votes. This loses ~1.84M votes (46% of total).

**Fix:** Sum all rows for a party in each afstemningsomraade (Partiliste + all candidate rows), not just the Partiliste row.

### Bug 2: AO name mismatch

FV2026 AO names include venue suffixes (e.g. "Agersoe - Agersoehallen") while FV2022 CSV has just "Agersoe". The `normalize_ao_name` function strips number prefixes but not venue suffixes. This causes 137 AOs to fail matching, losing ~210K votes. Slagelse is completely unmatched.

**Fix:** Strip venue suffixes (everything after " - ") from FV2026 AO names before matching.

### Validation

After fix, rebuild waves and verify:
- Total votes = 3,533,951 (DST official)
- All 92 opstillingskredse present
- Per-party vote totals match DST

## Workstream 2: Proper Tillaegsmandater Math

### Phase 1: National tillaeg allocation (40 seats)

New function `saint_lague_from_baseline(party_votes, n_seats, baselines)`:
- Sainte-Lague where each party's first divisor is `2k+1`, where `k` = kredsmandater already won
- A party with 10 kredsmandater starts at divisor 21; a party with 0 starts at 1
- Only qualifying parties participate (>=2% nationally OR >=1 kredsmandat)
- Allocates exactly 40 seats (TILLAEG_SEATS)

### Phase 2: Storkreds assignment of tillaeg seats

New function `dhondt_from_baseline(entity_votes, n_seats, baselines)`:
- D'Hondt where each entity's divisor starts at `baseline + 1`
- For each party that won tillaeg seats nationally, distribute those seats across storkredse
- Each storkreds baseline = kredsmandater that party already won in that storkreds

### Output structure

```python
{party_id: {
    "kreds": int,
    "tillaeg": int,
    "total": int,
    "kreds_by_storkreds": {storkreds_id: int},
    "tillaeg_by_storkreds": {storkreds_id: int},
}}
```

### Validation

Test with complete FV2022 data. Assert exact match against official DST results for all 14 parties:

| Party | Kreds | Tillaeg | Total |
|-------|------:|--------:|------:|
| A     |    50 |       0 |    50 |
| V     |    21 |       2 |    23 |
| M     |    13 |       3 |    16 |
| F     |    12 |       3 |    15 |
| AE    |    11 |       3 |    14 |
| I     |    10 |       4 |    14 |
| C     |     7 |       3 |    10 |
| OE    |     4 |       5 |     9 |
| B     |     2 |       5 |     7 |
| D     |     2 |       4 |     6 |
| AA    |     2 |       4 |     6 |
| O     |     1 |       4 |     5 |
| K     |     0 |       0 |     0 |
| Q     |     0 |       0 |     0 |

Run this validation before modifying the demo scenario.

## Workstream 3: Projection Layer

### When it activates

Whenever not all opstillingskredse have reported (< 100% reporting in any storkreds).

### Per-storkreds scaling

For each storkreds:
1. Calculate reporting fraction: `reported_votes / expected_votes`
2. `expected_votes` = sum of eligible voters x historical turnout rate for that storkreds (derived from FV2022 final totals or configurable)
3. Scale each party's storkreds votes: `projected_votes = actual_votes / reporting_fraction`
4. Feed projected storkreds votes into the proper tillaegsmandater math

### Edge cases

- **0% reported in a storkreds:** No projection for that storkreds (avoid division by zero). Seats come purely from whatever has reported.
- **Very low reporting (<10%):** Projection is computed but noisy. The reporting percentage label signals low confidence.
- **100% reported:** No scaling, use actual votes as-is.

### Reporting percentage

- National: `total_reported_votes / sum(expected_votes_per_storkreds)`
- Displayed as `Tillaeg [73% ind]` in CLI and API responses

### New function

```python
def project_storkreds_votes(
    storkreds_votes: dict[str, dict[str, int]],
    reporting_progress: dict[str, float],  # storkreds_id -> fraction [0, 1]
) -> dict[str, dict[str, int]]:
    """Scale partial storkreds votes to projected totals."""
```

## Integration & Display

### CLI `status` command

- Split current `Seats` column into `Kreds` and `Tillaeg [X% ind]`
- When 100% reported, label changes to just `Tillaeg`

### CLI `party` command

- Show per-storkreds breakdown: kredsmandater and tillaeg per storkreds
- Mark projected values with `[PROJ]`

### API response (`query_status`)

- Add fields: `kreds_seats`, `tillaeg_seats`, `reporting_pct`
- Keep `seats` as total for backwards compatibility

### Web dashboard

- Show split columns and reporting percentage, matching CLI

### Demo verification

- Before rebuilding demo waves, run validation test against official FV2022 results
- After rebuilding, verify demo works end-to-end

## Existing Plan

The existing plan at `docs/plans/2026-03-09-tillaegsmandater-plan.md` covers workstream 2 in detail (8 tasks). This spec extends it with the data fix (workstream 1) and projection layer (workstream 3). The implementation plan should incorporate relevant tasks from the existing plan.
