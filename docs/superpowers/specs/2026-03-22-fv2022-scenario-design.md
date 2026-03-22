# FV2022 Demo Scenario — Design Document

**Date:** 2026-03-22
**Scope:** Realistic Folketing election night demo scenario using FV2022 results and FV2026 geography/candidates
**Status:** Approved

---

## Problem

The existing `kv2025` demo scenario uses kommunalvalg data processed through the Folketing seat algorithm. This produces unrealistic results: parties like SF get 2–3 kredsmandater despite 11% of the national vote, because each kommune has only 1–3 seats and SF rarely wins a plurality. The scenario exercises the data pipeline but gives a misleading picture of how the algorithm behaves.

A `fv2022` scenario using real Folketing results across the real 10 storkredse will produce correct seat distributions and a realistic election night progression.

---

## Architecture

```
scripts/
  build_fv2022_scenario.py   ← one-time build script, run manually

valg/scenarios/
  fv2022.py                  ← Scenario module, same pattern as kv2025.py
  fv2022/
    wave_00/                 ← setup: geografi + kandidat-data
    wave_01/                 ← preliminary, tiny islands (21:03)
    wave_02/                 ← preliminary (21:14)
    ...
    wave_28/                 ← last preliminary batch (23:52)
    wave_29/                 ← fintælling batch 1 (00:20)
    ...
    wave_33/                 ← fintælling batch 5 (02:45)
```

Pre-built wave directories are committed to the code repo. The scenario module reads them at runtime — no build step required to run the demo.

---

## Data Sources

### Geography and candidates — FV2026 SFTP

From `data.valg.dk:/data/folketingsvalg-135-24-03-2026/`:

| File(s) | Used for |
|---|---|
| `geografi/Region-*.json` | → `storkredse` table (10 storkredse, integer IDs, `AntalKredsmandater`) |
| `geografi/Afstemningsomraade-*.json` | AO → opstillingskreds → storkreds hierarchy, `AntalStemmeberettigedeVælgere` for wave ordering |
| `geografi/Opstillingskreds-FV*.json` (inferred from geografi) | opstillingskredse integer IDs and names |
| `kandidat-data/kandidat-data-Folketingsvalg-{storkreds}-*.json` | Real FV2026 candidate UUIDs, names, ballot positions |
| `geografi/Parti-*.json` (if present) or derived | Party list |

The FV2026 data uses the same integer ID scheme as all other elections in the pipeline. Storkredse names are real ("Sjællands Storkreds", "Fyns Storkreds", etc.) with correct `AntalKredsmandater` (135 total across 10 storkredse).

### Vote results — FV2022 valg.dk API

```
GET https://valg.dk/api/export-data/export-fv-data-csv?electionId=987875fe-0dae-42ac-be5b-62cf0bd5d65e
```

Returns CSV (~169k rows):

```
Opstillingskreds;Afstemningsområde;Partibogstav;Partinavn;Navn;Stemmetal
Frederikshavnkredsen;1. Skagen;A;Socialdemokratiet;Partiliste;409
Frederikshavnkredsen;1. Skagen;A;Socialdemokratiet;Mette Frederiksen;926
```

- 92 opstillingskredse, 1,343 afstemningsomraader
- 14 party letters: A B C D F I K M O Q V Å Æ Ø
- `Navn = "Partiliste"` rows give party totals; other rows are per-candidate

Parties K, Q, Æ are minor parties with negligible vote shares. They are included but will fall below the 2% threshold and receive 0 seats.

---

## ID Mapping

The FV2022 CSV uses names; the FV2026 SFTP uses integer IDs. The build script maps them by normalised name matching:

1. Parse FV2026 `Afstemningsomraade-*.json` → dict `{(opstillingskreds_name_norm, ao_name_norm): ao_id}`
2. For each FV2022 CSV row, normalise `Opstillingskreds` and `Afstemningsområde` (lowercase, strip accents, collapse whitespace)
3. Look up FV2026 integer ID; skip with warning if no match
4. Log unmatched names to stdout — expect <2% mismatch due to minor naming changes between elections

The build script prints a summary of matched vs unmatched AOs before writing output.

---

## Wave Structure

### Overview (~34 waves)

| Wave | Time | Phase | Content | Description |
|---|---|---|---|---|
| 00 | 20:00 | setup | geografi, kandidat-data | Polls close |
| 01 | 21:03 | preliminary | partistemmefordeling, valgdeltagelse | Tiny islands (Bornholm, Læsø, Samsø, Ærø, Fanø, Anholt) |
| 02 | 21:11 | preliminary | partistemmefordeling, valgdeltagelse | Small rural (<500 voters) |
| 03 | 21:19 | preliminary | partistemmefordeling, valgdeltagelse | Small rural continued |
| 04 | 21:28 | preliminary | partistemmefordeling, valgdeltagelse | Rural towns |
| 05 | 21:38 | preliminary | partistemmefordeling, valgdeltagelse | Rural towns continued |
| 06 | 21:50 | preliminary | partistemmefordeling, valgdeltagelse | Small-medium (500–1000 voters) |
| 07 | 22:02 | preliminary | partistemmefordeling, valgdeltagelse | Small-medium continued |
| 08 | 22:14 | preliminary | partistemmefordeling, valgdeltagelse | Medium (1000–2000 voters) |
| 09 | 22:24 | preliminary | partistemmefordeling, valgdeltagelse | Medium continued |
| 10 | 22:33 | preliminary | partistemmefordeling, valgdeltagelse | Medium-large (2000–3000 voters) |
| 11 | 22:41 | preliminary | partistemmefordeling, valgdeltagelse | Medium-large continued |
| 12 | 22:48 | preliminary | partistemmefordeling, valgdeltagelse | Large (3000–4500 voters) |
| 13 | 22:54 | preliminary | partistemmefordeling, valgdeltagelse | Large continued |
| 14 | 22:59 | preliminary + final | partistemmefordeling, valgdeltagelse, valgresultater | Large + fintælling batch 1 (wave 01 AOs) |
| 15 | 23:05 | preliminary + final | partistemmefordeling, valgdeltagelse, valgresultater | Large + fintælling batch 2 (waves 02–03 AOs) |
| 16 | 23:11 | preliminary + final | partistemmefordeling, valgdeltagelse, valgresultater | Large continued + fintælling batch 3 |
| 17 | 23:18 | preliminary + final | partistemmefordeling, valgdeltagelse, valgresultater | Very large (4500–6000 voters) + fintælling |
| 18 | 23:25 | preliminary + final | partistemmefordeling, valgdeltagelse, valgresultater | Very large continued + fintælling |
| 19 | 23:32 | preliminary + final | partistemmefordeling, valgdeltagelse, valgresultater | Very large + fintælling batch 4 |
| 20 | 23:39 | preliminary + final | partistemmefordeling, valgdeltagelse, valgresultater | Urban large (6000–8000 voters) |
| 21 | 23:46 | preliminary + final | partistemmefordeling, valgdeltagelse, valgresultater | Urban large continued |
| 22 | 23:52 | preliminary + final | partistemmefordeling, valgdeltagelse, valgresultater | Urban large + fintælling batch 5 |
| 23 | 23:57 | preliminary | partistemmefordeling, valgdeltagelse | Last large urban AOs (>8000 voters) |
| 24 | 00:04 | preliminary | partistemmefordeling, valgdeltagelse | Copenhagen inner city, Aarhus C |
| 25 | 00:12 | preliminary | partistemmefordeling, valgdeltagelse | Last stragglers |
| 26 | 00:22 | final | valgresultater | Fintælling batch 6 (waves 04–06 AOs) |
| 27 | 00:40 | final | valgresultater | Fintælling batch 7 |
| 28 | 01:02 | final | valgresultater | Fintælling batch 8 |
| 29 | 01:28 | final | valgresultater | Fintælling batch 9 |
| 30 | 01:58 | final | valgresultater | Fintælling batch 10 |
| 31 | 02:31 | final | valgresultater | Fintælling batch 11 |
| 32 | 03:10 | final | valgresultater | Fintælling batch 12 — last urban AOs |

Total: 33 waves (wave_00 through wave_32). Extendable later by splitting any wave.

### Wave ordering logic

AOs are sorted by `AntalStemmeberettigedeVælgere` ascending. The build script:

1. Loads all AOs with their eligible voter counts from FV2026 SFTP
2. Sorts ascending
3. Splits into ~25 equal-count buckets for preliminary reporting
4. First buckets go to early waves; last buckets go to late waves
5. Tiny-island AOs (Bornholm storkreds, Samsø, Læsø) are manually placed in wave_01 regardless of size to mirror the known real-election pattern
6. Fintælling waves reuse AOs from preliminary waves in the same size order — small places finish counting faster

### `_meta.json` schema

```json
{
  "label": "21:03 — Bornholm, Læsø, Ærø, Fanø",
  "time": "21:03",
  "interval_s": 45.0,
  "phase": "preliminary"
}
```

`phase` is one of `"setup"`, `"preliminary"`, `"final"`.
`time` is wall-clock approximation of when this batch would arrive on a real election night.
`label` always leads with the time so it reads naturally in the step picker.

---

## File Formats Per Wave

### wave_00 (setup)

```
wave_00/
  _meta.json
  Parti-FV2022.json                           ← party list (letters + names)
  Storkreds.json                              ← 10 storkredse with AntalKredsmandater
  geografi/
    Opstillingskreds-FV2022.json              ← 92 opstillingskredse with StorkredskodeKode
    Afstemningsomraade-FV2022.json            ← all AOs with opstillingskreds link
  kandidat-data/
    kandidat-data-Folketingsvalg-1-Kbh.json   ← one file per storkreds (FV2026 candidates)
    kandidat-data-Folketingsvalg-2-...json
    ...
```

### Preliminary waves (wave_01–wave_25)

```
wave_NN/
  _meta.json
  partistemmefordeling/
    partistemmefordeling-{ok_id}.json     ← one per opstillingskreds with ≥1 AO in this wave
  valgdeltagelse/
    valgdeltagelse-{ao_id}.json           ← one per AO in this wave
```

`partistemmefordeling` is **cumulative** — contains running totals for all AOs in that opstillingskreds reported so far (same as live data behaviour). Each wave re-emits updated files for affected opstillingskredse.

### Fintælling waves (wave_14–wave_32, mixed or pure final)

```
wave_NN/
  _meta.json
  partistemmefordeling/           ← present only if also has preliminary AOs
    ...
  valgdeltagelse/                 ← present only if also has preliminary AOs
    ...
  valgresultater/
    valgresultater-Folketingsvalg-{ao_name}-{ao_id}.json   ← one per final AO
```

`valgresultater` format (final):

```json
{
  "Valgresultater": {
    "AfstemningsomraadeId": "706986",
    "Optaellingstype": "Fintaelling",
    "IndenforParti": [
      {
        "PartiId": "A",
        "Partistemmer": 247,
        "Kandidater": [
          {"KandidatId": "uuid-from-fv2026", "Stemmer": 86},
          {"KandidatId": "uuid-from-fv2026", "Stemmer": 34},
          ...
        ]
      }
    ],
    "KandidaterUdenforParti": []
  }
}
```

---

## Candidate Vote Distribution

FV2022 candidate names and FV2026 candidate UUIDs are different people — no reliable name mapping exists. Candidate votes are therefore synthetic, derived from FV2022 party totals:

For each AO × party:
1. Take `Partistemmer` from FV2022 CSV for that AO + party
2. Look up FV2026 candidates for that party in the relevant opstillingskreds, sorted by `Stemmeseddelplacering` (ballot position)
3. Distribute votes:
   - Position 1 (kredskandidat): 35% of party votes
   - Remaining candidates: 65% split with weight `1 / position^0.7` (power decay)
   - Round to integers; assign remainder to position 1
   - Minimum 0 votes per candidate

This produces realistic-looking distributions: kredskandidat dominates, a few candidates get meaningful personal votes, tail candidates get 0–5.

If an opstillingskreds has no FV2026 candidates for a party (party not standing there), `Kandidater: []` for that party.

---

## Scenario Module

`valg/scenarios/fv2022.py` follows the exact same pattern as `kv2025.py`:

```python
WAVE_DIR = Path(__file__).parent / "fv2022"

def _copy_wave(wave_dir: Path, data_repo: Path) -> list[Path]:
    dest = data_repo / "demo" / "fv2022"
    # copy files from wave_dir subdirs into dest, preserving subdir structure
    # skip _meta.json
    # return list of written paths

def _make_steps(data_repo: Path) -> list[Step]:
    steps = []
    for wave_dir in sorted(WAVE_DIR.glob("wave_*")):
        meta = json.loads((wave_dir / "_meta.json").read_text())
        steps.append(Step(
            name=meta["label"],
            wave=None,
            setup=(meta["phase"] == "setup"),
            write_fn=lambda d, src=wave_dir: _copy_wave(src, d),
            base_interval_s=meta["interval_s"],
        ))
    return steps

FV2022_SCENARIO = Scenario(
    name="FV2022 — Folketing 1. november 2022",
    description="Rigtige stemmeresultater fra Folketingsvalget 2022, afspillet som valgaften.",
    steps_factory=_make_steps,
)
```

Registration in `valg/demo.py`:

```python
from valg.scenarios.fv2022 import FV2022_SCENARIO
SCENARIOS["fv2022"] = FV2022_SCENARIO
```

---

## Build Script

`scripts/build_fv2022_scenario.py` — run once manually, output committed.

### Phases

**Phase 1 — Download**
- SFTP: download `geografi/`, `kandidat-data/` from FV2026 folder into `scripts/.cache/fv2026/`
- HTTP GET FV2022 CSV → `scripts/.cache/fv2022_results.csv`
- Cache is checked before downloading — re-running skips downloads if cache exists (`--force` to override)

**Phase 2 — Parse and map**
- Parse FV2026 geografi files → hierarchy dict `{ao_id: {ao_name, ok_id, ok_name, sk_id, sk_name, eligible_voters}}`
- Parse FV2026 kandidat-data → dict `{ok_id: {party_id: [candidates sorted by ballot_pos]}}`
- Parse FV2022 CSV → `{(ok_name_norm, ao_name_norm): {party_id: {total, candidates: [{name, votes}]}}}`
- Name-join: map each FV2022 (ok_name, ao_name) pair to a FV2026 `ao_id`
- Print match summary: `Matched 1289/1343 AOs (96.0%)`

**Phase 3 — Wave assignment**
- Sort matched AOs by `eligible_voters` ascending
- Manually assign Bornholm storkreds AOs + Læsø + Samsø + Ærø + Fanø + Anholt to wave_01
- Assign remaining AOs to waves 02–25 in equal-count buckets (~50–60 AOs per wave)
- Assign each AO a fintælling wave (same order, offset by ~14 waves)
- Compute `interval_s` for each wave from the time column above

**Phase 4 — Write**
- Clear `valg/scenarios/fv2022/` if exists
- Write `wave_00/`: Parti, Storkreds, geografi, kandidat-data files
- For each preliminary wave: write `partistemmefordeling/` (cumulative) and `valgdeltagelse/`
- For each fintælling wave: write `valgresultater/` with synthetic candidate votes
- Write `_meta.json` for every wave

---

## Out of Scope

- Live recording of FV2026 election night data (separate future task)
- Accurate candidate-level historical accuracy (candidate votes are synthetic)
- Regionsrådsvalg (ignored)
- Valgforbund (not present in Folketing elections)
- Expanding waves beyond 33 (can split any wave later with the build script)
