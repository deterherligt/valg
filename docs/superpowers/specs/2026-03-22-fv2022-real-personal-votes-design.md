# FV2022 Scenario — Real Personal Votes

**Date:** 2026-03-22
**Scope:** Replace synthetic candidate vote distribution in the FV2022 demo scenario with real personal votes from the FV2022 election.

---

## Problem

The FV2022 demo scenario currently uses FV2026 candidates in `wave_00` and synthetically distributes candidate votes in fintælling waves (26–32) using a 35%/power-decay algorithm. Personal votes shown in the UI are fabricated, not real.

## Goal

Use real FV2022 kandidat-data (real candidate IDs and names) and real per-candidate, per-polling-station personal vote counts throughout the scenario.

---

## Data Sources

### FV2022 Kandidat-data

Source: SFTP at `data.valg.dk:22` (credentials: `Valg/Valg`), expected archive path `/arkiv/FV2022/kandidat-data/` (to be verified during implementation — the election is also indexed at `https://valg.dk/fv/987875fe-0dae-42ac-be5b-62cf0bd5d65e`).

Format: same JSON struktur as FV2026 kandidat-data (already parsed by `parse_kandidatdata()`).

### FV2022 Personal Votes

Source: existing CSV export (`https://valg.dk/api/export-data/export-fv-data-csv?electionId=987875fe-0dae-42ac-be5b-62cf0bd5d65e`), already cached by the build script.

The CSV contains one row per (candidate, afstemningsområde). Rows with `Navn == "Partiliste"` are party-list votes (already parsed). Rows with `Navn != "Partiliste"` are personal votes — currently skipped.

Key CSV columns for personal votes: `Navn` (candidate name), `Opstillingskreds`, `Afstemningsområde`, `Partibogstav`, `Stemmetal`.

---

## Changes to `scripts/build_fv2022_scenario.py`

### 1. Download FV2022 kandidat-data

Add `download_fv2022_kandidatdata(force: bool)`:
- Downloads to `.cache/fv2022/kandidat-data/`
- Same SFTP download pattern as existing `download_fv2026_kandidatdata()`
- Path to verify: `/arkiv/FV2022/kandidat-data/` or equivalent

Add call in `download_all()`.

### 2. Parse FV2022 kandidat-data

Add `parse_fv2022_kandidatdata(kd_dir: Path) -> dict[str, dict[str, list[dict]]]`:
- Same logic and return structure as existing `parse_kandidatdata()`
- Returns `{ok_id: {party_id: [{id, name, ballot_position}]}}`
- `ok_id` is `OpstillingskredsDagiId` from FV2022 kandidat-data

### 3. Parse personal votes from CSV

Add `parse_fv2022_personal_votes(csv_path: Path) -> dict[tuple[str, str], dict[str, dict[str, int]]]`:
- Reads all CSV rows where `Navn != "Partiliste"`
- Returns `{(ok_norm, ao_norm): {party_id: {name_norm: votes}}}`
- Uses same `normalize_ok_name` / `normalize_ao_name` as existing CSV parser
- Candidate name normalized with `normalize_name()`

### 4. Update `write_wave_00()`

- Change kandidat-data source from `.cache/fv2026/kandidat-data/` to `.cache/fv2022/kandidat-data/`
- No other changes to wave_00 structure

### 5. Update `write_fintaelling_wave()`

Replace the `distribute_candidate_votes` call with a real-vote lookup:

For each AO in the wave:
- Look up `personal_votes[(ok_norm, ao_norm)][party_id]` → `{name_norm: votes}`
- For each candidate in FV2022 kandidat-data for this party+ok: look up by `normalize_name(candidate["name"])`
- Candidate found → use real vote count
- Candidate not found → 0 votes (and record as unmatched)
- `Partistemmer` is unchanged (party total from `fv2022_votes`, includes both list and personal votes)

After writing all waves, print a summary of unmatched candidates (count + examples) so mismatches are visible during the build, not silent.

### 6. Update `run()`

- Pass FV2022 kandidat-data dir to `parse_fv2022_kandidatdata()`
- Pass personal votes to `write_fintaelling_wave()`

---

## ID Matching

FV2022 kandidat-data provides real candidate IDs and names keyed by `OpstillingskredsDagiId`. The geography (AO→ok mapping) uses FV2026 `Dagi_id` values, which should match since the geography is stable across elections. If the FV2022 SFTP path uses different ok IDs, a name-based fallback mapping is needed — to be determined during implementation.

---

## Wave Structure

No changes to wave count, intervals, or file layout. Only the content of `valgresultater/*.json` files in waves 26–32 changes: `Kandidater[i].Stemmer` values are real instead of synthetic.

---

## Out of Scope

- Adding `valgresultater` to preliminary waves (01–25)
- Changing party vote totals in `partistemmefordeling`
- Any UI changes
