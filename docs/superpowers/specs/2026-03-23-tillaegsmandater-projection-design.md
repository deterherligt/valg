# Tillægsmandater Projection Design

## Problem

The valg dashboard currently approximates tillægsmandater by subtracting kredsmandater from a national modified Saint-Lague allocation of all 175 seats. This is inaccurate because:

1. The national allocation should use Hare quota + largest remainder, not modified Saint-Lague (Folketingsvalglov §77)
2. Tillaegsmandat distribution to landsdele (§78) and storkredse (§79) is not computed
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

The Danish Folketingsvalg seat allocation follows Folketingsvalglov §76-§79. Four distinct steps, each using a different method.

### Step 1: Kredsmandater — D'Hondt per storkreds (§76)

Already implemented correctly. D'Hondt (divisors 1, 2, 3, 4...) per storkreds, 135 seats total.

### Step 2: National proportional allocation — Hare quota + largest remainder (§77)

New function `hare_largest_remainder(party_votes, n_seats)`:
- Compute Hare quota: `Q = total_qualifying_votes / n_seats`
- Each party gets `floor(votes / Q)` seats automatically
- Remaining seats go to parties with the largest fractional remainders
- Only qualifying parties participate (>=2% nationally OR >=1 kredsmandat)
- Allocates all 175 seats

**Replaces** the current `modified_saint_lague` call in `allocate_seats_total`.

### Overhang rule (§77 stk. 4-5)

If a party wins more kredsmandater than its national Hare allocation, it keeps all kredsmandater and receives 0 tillaeg. The excess reduces the pool for remaining parties, who are recalculated excluding the over-represented party.

In FV2022: Socialdemokratiet won 50 kredsmandater but was entitled to only 49 nationally. They kept 50, got 0 tillaeg. The remaining 125 seats (175-50) were redistributed among the other qualifying parties.

### Step 3: Distribute tillaeg to landsdele — Sainte-Lague with exclusions (§78)

New function `allocate_tillaeg_to_landsdele(party_landsdel_votes, tillaeg_per_party, kreds_per_party_per_landsdel)`:
- For each party, divide their votes in each of the 3 landsdele by Sainte-Lague divisors (1, 3, 5, 7...)
- For each party-landsdel combination, the first `k` quotients (where k = kredsmandater already won in that landsdel) are "reserved" / excluded
- Rank the remaining quotients across all party-landsdel pairs
- Assign tillaeg seats to the highest quotients until all 40 are distributed

The 3 landsdele and their storkredse (fixed by law):
- **Hovedstaden:** Kobenhavns, Kobenhavns Omegns, Nordsjaellands, Bornholms Storkreds
- **Sjaelland-Syddanmark:** Sjaellands, Fyns, Sydjyllands Storkreds
- **Midtjylland-Nordjylland:** Ostjyllands, Vestjyllands, Nordjyllands Storkreds

This mapping is hardcoded in the calculator as `LANDSDEL_STORKREDSE`.

### Step 4: Distribute tillaeg to storkredse within landsdel — Danish method (§79)

New function `allocate_tillaeg_to_storkredse(party_storkreds_votes, tillaeg_per_party_per_landsdel, kreds_per_party_per_storkreds)`:
- For each party-landsdel pair that received tillaeg seats, distribute them to storkredse within that landsdel
- Divisors: 1, 4, 7, 10, 13... (first divisor 1, increment 3)
- Same exclusion logic: first `k` quotients reserved for each storkreds where the party already won `k` kredsmandater
- Highest remaining quotient gets the seat

### Data requirements

The calculator needs per-landsdel vote totals. Since landsdele are just groupings of storkredse, compute `landsdel_votes` by summing `storkreds_votes` per the hardcoded mapping. No schema change needed.

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

Test with complete FV2022 data. Assert exact match against official DST results for all parties:

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
| O     |     5 |       0 |     5 |
| K     |     0 |       0 |     0 |
| Q     |     0 |       0 |     0 |

Note: A (Socialdemokratiet) has overhang — 50 kredsmandater but only 49 Hare allocation. They keep all 50 kreds and get 0 tillaeg, triggering the §77 stk. 4-5 recalculation. O (Dansk Folkeparti) gets exactly 5 kreds = 5 Hare allocation — no overhang, but 0 tillaeg. The overhang recalculation only triggers when `kreds > hare_seats`, not `kreds >= hare_seats`.

Run this validation before modifying the demo scenario.

## Workstream 3: Projection Layer

### When it activates

Whenever not all opstillingskredse have reported (< 100% reporting in any storkreds).

### Per-storkreds scaling

For each storkreds:
1. Calculate reporting fraction: `reported_votes / expected_votes`
2. `expected_votes` per storkreds: sum `eligible_voters` from `afstemningsomraader` table (joined through `opstillingskredse`) multiplied by a turnout estimate
3. Turnout estimate: hardcoded constant (0.84 based on FV2022 national turnout of 84.16%), configurable per-storkreds in a future iteration
4. Scale each party's storkreds votes: `projected_votes = actual_votes / reporting_fraction`
5. Feed projected storkreds votes into the proper tillaegsmandater math

### Reporting progress query

```python
def get_reporting_progress(conn) -> dict[str, float]:
    """Return {storkreds_id: fraction} based on votes in vs expected."""
```

Query: for each storkreds, sum `eligible_voters` from all its AOs (via opstillingskredse join) as the denominator. For the numerator, sum votes from `party_votes` latest snapshot per opstillingskreds, then multiply by the turnout estimate to get the expected vote total. The reporting fraction is `reported_votes / (eligible_voters * turnout_estimate)`. Cap at 1.0.

### Edge cases

- **0% reported in a storkreds:** No projection for that storkreds (avoid division by zero). Its parties contribute zero projected votes. This is conservative but honest.
- **Very low reporting (<10%):** Projection is computed but noisy. The reporting percentage label signals low confidence.
- **100% reported:** No scaling, use actual votes as-is.
- **Reporting fraction > 1.0:** Cap at 1.0 (can happen if eligible_voters is stale or turnout exceeds estimate). Use actual votes.

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

### API responses

- `query_status`: add fields `kreds_seats`, `tillaeg_seats`, `reporting_pct`. Keep `seats` as total for backwards compatibility.
- `query_api_parties` and `query_api_party_detail`: update to use `allocate_seats_detail` instead of `allocate_seats_total`

### Web dashboard

- Show split columns and reporting percentage, matching CLI

### Demo verification

- Before rebuilding demo waves, run validation test against official FV2022 results
- After rebuilding, verify demo works end-to-end

## Known Limitations

- **Third threshold criterion not implemented:** Danish law allows qualification via sufficient signatures in two of three landsdele. The code only checks 2% national or 1 kredsmandat. This matches the current codebase and is unlikely to matter in practice.
- **Flip functions (`votes_to_gain_seat` / `votes_to_lose_seat`):** These use `allocate_seats_total` internally. After refactoring, they automatically use the proper math. The vote-addition strategy (distributing delta across storkredse) remains approximate but acceptable for signalling purposes.
- **Turnout estimate:** Using a fixed 0.84 nationally. Per-storkreds historical turnout would improve early projections but adds complexity. Deferred.

## Existing Plan

The existing plan at `docs/plans/2026-03-09-tillaegsmandater-plan.md` covers parts of workstream 2 but uses incorrect algorithms (Saint-Lague 2k+1 baseline, D'Hondt for storkreds assignment). The implementation plan derived from this spec supersedes that plan.
