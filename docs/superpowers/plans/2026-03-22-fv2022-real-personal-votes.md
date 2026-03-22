# FV2022 Real Personal Votes — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace synthetic candidate vote distribution in the FV2022 demo scenario with real FV2022 kandidat-data and real per-candidate personal votes from every polling station.

**Architecture:** The build script `scripts/build_fv2022_scenario.py` is the only file changed. It gains a new download function for FV2022 kandidat-data, a new CSV parser for personal vote rows, and a refactored `build_valgresultater` that accepts pre-built kandidater instead of distributing votes synthetically. `wave_00` switches from FV2026 to FV2022 kandidat-data; fintælling waves (26–32) get real vote counts.

**Tech Stack:** Python stdlib only (`csv`, `json`, `pathlib`, `shutil`). SFTP via `paramiko`. Tests in `pytest` with `tmp_path`.

---

## Files

- Modify: `scripts/build_fv2022_scenario.py`
- Modify: `tests/test_fv2022_build.py`

---

### Task 1: Discover FV2022 SFTP path and add download function

The FV2022 kandidat-data lives in the SFTP archive. First confirm the path, then add the download function.

**Files:**
- Modify: `scripts/build_fv2022_scenario.py`

- [ ] **Step 1: Explore SFTP to find the FV2022 archive path**

Run the existing explore script:
```bash
python scripts/download_historical.py
```
Look for an entry like `/arkiv/FV2022/` or `/data/folketingsvalg-1-2022/` in the output. Find the subdirectory containing `kandidat-data/`. Note the exact path — you'll need it in the next step.

Expected output: a tree of SFTP paths printed to stdout. Find the one for FV2022.

- [ ] **Step 2: Write a failing test for `download_fv2022_kandidatdata`**

Add to `tests/test_fv2022_build.py`:

```python
def test_download_fv2022_kandidatdata_creates_cache_dir(tmp_path, monkeypatch):
    """download_fv2022_kandidatdata creates target dir and calls sftp download."""
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
    from build_fv2022_scenario import download_fv2022_kandidatdata
    import build_fv2022_scenario as script

    calls = []
    def fake_download(force=False):
        calls.append(force)
        (script.CACHE_DIR / "fv2022" / "kandidat-data").mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(script, "CACHE_DIR", tmp_path / ".cache")
    monkeypatch.setattr(script, "_do_sftp_download_fv2022_kd", fake_download)
    download_fv2022_kandidatdata(force=False)
    assert (tmp_path / ".cache" / "fv2022" / "kandidat-data").exists()
    assert calls == [False]
```

Run: `pytest tests/test_fv2022_build.py::test_download_fv2022_kandidatdata_creates_cache_dir -v`
Expected: FAIL with `ImportError` or `AttributeError` (function doesn't exist yet).

- [ ] **Step 3: Add `download_fv2022_kandidatdata` to the build script**

In `scripts/build_fv2022_scenario.py`, add the SFTP path constant near the top (after `FV2026_SFTP_PATH`):

```python
FV2022_SFTP_PATH = "/arkiv/FV2022"   # ← replace with exact path found in Step 1
```

Then add the download function (after `download_fv2026_kandidatdata`):

```python
def _do_sftp_download_fv2022_kd(force: bool = False) -> None:
    """Internal: SFTP download of FV2022 kandidat-data into cache."""
    import paramiko
    local_kd = CACHE_DIR / "fv2022" / "kandidat-data"
    local_kd.mkdir(parents=True, exist_ok=True)

    if not force and any(local_kd.glob("*.json")):
        print(f"  using cached fv2022/kandidat-data/ ({len(list(local_kd.glob('*.json')))} files)")
        return

    print("  downloading fv2022/kandidat-data from SFTP …")
    transport = paramiko.Transport(("data.valg.dk", 22))
    transport.connect(username="Valg", password="Valg")
    sftp = paramiko.SFTPClient.from_transport(transport)
    try:
        count = download_sftp_dir(sftp, f"{FV2022_SFTP_PATH}/kandidat-data", local_kd, force=force)
        if count == 0 and not any(local_kd.glob("*.json")):
            raise RuntimeError(
                f"No kandidat-data files found at {FV2022_SFTP_PATH}/kandidat-data — "
                "check FV2022_SFTP_PATH in the build script."
            )
        print(f"  downloaded {count} fv2022 kandidat-data files")
    finally:
        sftp.close()
        transport.close()


def download_fv2022_kandidatdata(force: bool = False) -> None:
    """Download FV2022 kandidat-data from SFTP into cache."""
    _do_sftp_download_fv2022_kd(force=force)
```

Also update `download_all()` to call it:

```python
def download_all(force: bool = False) -> None:
    print("Phase 1: Downloading data …")
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    download_fv2026_geografi(force=force)
    download_fv2022_kandidatdata(force=force)   # ← add this line
    download_fv2022_csv(force=force)
    print()
```

Also remove the existing call to `download_fv2026_kandidatdata` from `download_all()` — it's no longer needed.

- [ ] **Step 4: Run the test**

Run: `pytest tests/test_fv2022_build.py::test_download_fv2022_kandidatdata_creates_cache_dir -v`
Expected: PASS.

- [ ] **Step 5: Smoke-test the download against real SFTP**

```bash
python scripts/build_fv2022_scenario.py --force 2>&1 | head -20
```

Expected: prints something like `downloaded N fv2022 kandidat-data files`. If it prints `0` and raises RuntimeError, the `FV2022_SFTP_PATH` is wrong — go back to Step 1 and check the actual path.

- [ ] **Step 6: Commit**

```bash
git add scripts/build_fv2022_scenario.py tests/test_fv2022_build.py
git commit -m "feat: add download_fv2022_kandidatdata from SFTP archive"
```

---

### Task 2: Add `parse_fv2022_personal_votes`

Parse the personal vote rows from the already-downloaded FV2022 CSV. These are rows where `Navn != "Partiliste"`.

**Files:**
- Modify: `scripts/build_fv2022_scenario.py`
- Modify: `tests/test_fv2022_build.py`

- [ ] **Step 1: Write a failing test**

Add to `tests/test_fv2022_build.py`:

```python
def test_parse_fv2022_personal_votes_extracts_candidate_rows(tmp_path):
    """parse_fv2022_personal_votes returns {(ok_norm, ao_norm): {party_id: {name_norm: votes}}}."""
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
    from build_fv2022_scenario import (
        parse_fv2022_personal_votes, normalize_ok_name, normalize_ao_name, normalize_name,
    )

    csv_file = tmp_path / "results.csv"
    csv_file.write_text(
        "Opstillingskreds;Afstemningsområde;Partibogstav;Partinavn;Navn;Stemmetal\n"
        "Frederikshavnkredsen;1. Skagen;A;Socialdemokratiet;Partiliste;409\n"
        "Frederikshavnkredsen;1. Skagen;A;Socialdemokratiet;Mette Frederiksen;926\n"
        "Frederikshavnkredsen;1. Skagen;A;Socialdemokratiet;Peter Skaarup;12\n"
        "Frederikshavnkredsen;1. Skagen;V;Venstre;Partiliste;281\n"
        "Frederikshavnkredsen;1. Skagen;V;Venstre;Jakob Ellemann-Jensen;55\n",
        encoding="utf-8-sig",
    )

    result = parse_fv2022_personal_votes(csv_file)
    key = (normalize_ok_name("Frederikshavnkredsen"), normalize_ao_name("1. Skagen"))
    assert key in result
    # Partiliste rows excluded
    assert "partiliste" not in result[key].get("A", {})
    # Candidate votes present
    assert result[key]["A"][normalize_name("Mette Frederiksen")] == 926
    assert result[key]["A"][normalize_name("Peter Skaarup")] == 12
    assert result[key]["V"][normalize_name("Jakob Ellemann-Jensen")] == 55


def test_parse_fv2022_personal_votes_skips_partiliste():
    """parse_fv2022_personal_votes never includes Partiliste rows."""
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
    from build_fv2022_scenario import parse_fv2022_personal_votes
    import tempfile, os

    with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False, encoding="utf-8-sig") as f:
        f.write("Opstillingskreds;Afstemningsområde;Partibogstav;Partinavn;Navn;Stemmetal\n")
        f.write("Kreds1;AO1;A;SD;Partiliste;100\n")
        fname = f.name

    try:
        result = parse_fv2022_personal_votes(Path(fname))
        for ao_parties in result.values():
            for party_votes in ao_parties.values():
                assert "partiliste" not in party_votes
    finally:
        os.unlink(fname)
```

Run: `pytest tests/test_fv2022_build.py::test_parse_fv2022_personal_votes_extracts_candidate_rows -v`
Expected: FAIL with `ImportError`.

- [ ] **Step 2: Add `parse_fv2022_personal_votes` to the build script**

Add after `parse_fv2022_csv` (around line 377):

```python
def parse_fv2022_personal_votes(
    csv_path: Path,
) -> dict[tuple[str, str], dict[str, dict[str, int]]]:
    """
    Parse FV2022 personal vote rows from the CSV.

    Returns {(ok_norm, ao_norm): {party_id: {name_norm: votes}}}
    Skips Partiliste rows (those are party-list votes, not personal votes).
    """
    result: dict[tuple[str, str], dict[str, dict[str, int]]] = {}
    with csv_path.open(encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f, delimiter=";")
        for row in reader:
            navn = row.get("Navn", "").strip()
            if navn == "Partiliste":
                continue
            ok_norm = normalize_ok_name(row.get("Opstillingskreds", ""))
            ao_norm = normalize_ao_name(row.get("Afstemningsområde", ""))
            party_id = row.get("Partibogstav", "").strip()
            name_norm = normalize_name(navn)
            try:
                votes = int(row.get("Stemmetal", 0))
            except (ValueError, TypeError):
                continue
            result.setdefault((ok_norm, ao_norm), {}).setdefault(party_id, {})[name_norm] = votes
    return result
```

- [ ] **Step 3: Run the tests**

Run: `pytest tests/test_fv2022_build.py::test_parse_fv2022_personal_votes_extracts_candidate_rows tests/test_fv2022_build.py::test_parse_fv2022_personal_votes_skips_partiliste -v`
Expected: both PASS.

- [ ] **Step 4: Run full test suite**

Run: `pytest tests/test_fv2022_build.py -v`
Expected: all existing tests still pass.

- [ ] **Step 5: Commit**

```bash
git add scripts/build_fv2022_scenario.py tests/test_fv2022_build.py
git commit -m "feat: parse real personal votes from FV2022 CSV"
```

---

### Task 3: Refactor `build_valgresultater` — accept pre-built kandidater

Currently `build_valgresultater` takes `candidates_by_ok` and calls `distribute_candidate_votes` internally. Change it to accept a pre-built kandidater list so the caller controls vote counts. Remove `distribute_candidate_votes` (dead code after this change).

**Files:**
- Modify: `scripts/build_fv2022_scenario.py`
- Modify: `tests/test_fv2022_build.py`

- [ ] **Step 1: Update the test for `build_valgresultater`**

In `tests/test_fv2022_build.py`, replace `test_build_valgresultater_structure`:

```python
def test_build_valgresultater_structure():
    from build_fv2022_scenario import build_valgresultater
    party_data = {
        "A": {
            "total": 100,
            "kandidater": [
                {"KandidatId": "uuid-1", "Stemmer": 40},
                {"KandidatId": "uuid-2", "Stemmer": 15},
            ],
        }
    }
    result = build_valgresultater(
        ao_id="706986",
        optaellingstype="Fintaelling",
        party_data=party_data,
    )
    vr = result["Valgresultater"]
    assert vr["AfstemningsomraadeId"] == "706986"
    assert vr["Optaellingstype"] == "Fintaelling"
    party_a = next(p for p in vr["IndenforParti"] if p["PartiId"] == "A")
    assert party_a["Partistemmer"] == 100
    assert party_a["Kandidater"] == [
        {"KandidatId": "uuid-1", "Stemmer": 40},
        {"KandidatId": "uuid-2", "Stemmer": 15},
    ]
```

Also remove `test_distribute_votes_sums_to_party_total`, `test_distribute_votes_position_one_gets_most`, `test_distribute_votes_position_one_gets_35_percent`, `test_distribute_votes_zero_party_total`, `test_distribute_votes_empty_candidates` — `distribute_candidate_votes` is being deleted.

Run: `pytest tests/test_fv2022_build.py::test_build_valgresultater_structure -v`
Expected: FAIL (function signature changed).

- [ ] **Step 2: Refactor `build_valgresultater`**

Replace the existing `build_valgresultater` function (and delete `distribute_candidate_votes`):

```python
def build_valgresultater(
    ao_id: str,
    optaellingstype: str,
    party_data: dict[str, dict],
) -> dict:
    """Build a valgresultater JSON structure for one AO.

    party_data: {party_id: {"total": int, "kandidater": [{"KandidatId": str, "Stemmer": int}]}}
    """
    inden_for_parti = [
        {
            "PartiId": party_id,
            "Partistemmer": pdata["total"],
            "Kandidater": pdata.get("kandidater", []),
        }
        for party_id, pdata in party_data.items()
    ]
    return {
        "Valgresultater": {
            "AfstemningsomraadeId": str(ao_id),
            "Optaellingstype": optaellingstype,
            "IndenforParti": inden_for_parti,
            "KandidaterUdenforParti": [],
        }
    }
```

Delete the `distribute_candidate_votes` function entirely.

- [ ] **Step 3: Run the tests**

Run: `pytest tests/test_fv2022_build.py -v`
Expected: all pass (the removed `distribute_candidate_votes` tests are gone; the updated `build_valgresultater` test passes).

- [ ] **Step 4: Commit**

```bash
git add scripts/build_fv2022_scenario.py tests/test_fv2022_build.py
git commit -m "refactor: build_valgresultater accepts pre-built kandidater, remove synthetic distribution"
```

---

### Task 4: Update `write_wave_00` to use FV2022 kandidat-data

`wave_00` sets up the election by copying kandidat-data. Currently it uses FV2026. Switch it to use the FV2022 kandidat-data downloaded in Task 1.

**Files:**
- Modify: `scripts/build_fv2022_scenario.py`

- [ ] **Step 1: Update `write_wave_00`**

In `write_wave_00`, find the block that copies kandidat-data:

```python
    kd_out = wave_dir / "kandidat-data"
    kd_out.mkdir(exist_ok=True)
    for src in kandidat_dir.glob("*.json"):
        if not src.name.endswith(".hash"):
            shutil.copy2(src, kd_out / src.name)
```

This block already uses the `kandidat_dir` parameter passed to the function — no code change is needed here. The fix is in `run()` (Task 6): pass `CACHE_DIR / "fv2022" / "kandidat-data"` instead of `CACHE_DIR / "fv2026" / "kandidat-data"`.

No code change to `write_wave_00` itself. Just confirm the function signature already takes `kandidat_dir: Path` — it does (line ~537 in the build script).

- [ ] **Step 2: Confirm with a quick read**

Read `scripts/build_fv2022_scenario.py` lines 537–580 and confirm `write_wave_00(output_dir, geografi_dir, kandidat_dir, ...)` takes `kandidat_dir` as a parameter. The path passed at call-site in `run()` is what matters — that's handled in Task 6.

No commit needed for this task — the change is trivial and will be bundled with Task 6.

---

### Task 5: Update `write_fintaelling_wave` to use real votes

Replace the synthetic candidate vote lookup with a real-vote lookup using the FV2022 kandidat-data and parsed personal votes.

**Files:**
- Modify: `scripts/build_fv2022_scenario.py`
- Modify: `tests/test_fv2022_build.py`

- [ ] **Step 1: Write a failing test for the real-vote path**

Add to `tests/test_fv2022_build.py`:

```python
def test_write_fintaelling_wave_uses_real_votes(tmp_path):
    """write_fintaelling_wave writes valgresultater with real personal votes."""
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
    from build_fv2022_scenario import write_fintaelling_wave
    import json

    hierarchy = {
        "701001": {
            "ao_name": "1. Skagen",
            "ok_id": "100101",
            "ok_name": "Frederikshavnkredsen",
            "sk_id": "1",
            "sk_name": "Nordjylland",
            "eligible_voters": 500,
        }
    }
    from build_fv2022_scenario import normalize_ok_name, normalize_ao_name
    ok_norm = normalize_ok_name("Frederikshavnkredsen")
    ao_norm = normalize_ao_name("1. Skagen")
    fv2022_votes = {
        (ok_norm, ao_norm): {"A": 200, "V": 150},
    }
    # Real personal votes: Mette got 80, Peter got 30 out of A's 200 total
    personal_votes = {
        (ok_norm, ao_norm): {
            "A": {"mette frederiksen": 80, "peter skaarup": 30},
            "V": {"jakob ellemann-jensen": 55},
        }
    }
    fv2022_kandidatdata = {
        "100101": {
            "A": [
                {"id": "cand-1", "name": "Mette Frederiksen", "ballot_position": 1},
                {"id": "cand-2", "name": "Peter Skaarup", "ballot_position": 2},
            ],
            "V": [
                {"id": "cand-3", "name": "Jakob Ellemann-Jensen", "ballot_position": 1},
            ],
        }
    }

    wave_dir = tmp_path / "wave_26"
    write_fintaelling_wave(
        wave_dir=wave_dir,
        wave_index=26,
        ao_ids_in_wave=["701001"],
        hierarchy=hierarchy,
        fv2022_votes=fv2022_votes,
        kandidatdata=fv2022_kandidatdata,
        personal_votes=personal_votes,
    )

    vr_files = list((wave_dir / "valgresultater").glob("*.json"))
    assert len(vr_files) == 1
    vr = json.loads(vr_files[0].read_text())["Valgresultater"]
    party_a = next(p for p in vr["IndenforParti"] if p["PartiId"] == "A")
    assert party_a["Partistemmer"] == 200
    cand_votes = {k["KandidatId"]: k["Stemmer"] for k in party_a["Kandidater"]}
    assert cand_votes["cand-1"] == 80
    assert cand_votes["cand-2"] == 30


def test_write_fintaelling_wave_zero_for_unmatched_candidate(tmp_path):
    """Candidates with no personal vote entry get Stemmer=0."""
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
    from build_fintaelling_wave import write_fintaelling_wave
    import json

    hierarchy = {
        "701001": {
            "ao_name": "Test AO",
            "ok_id": "ok1",
            "ok_name": "Test Kreds",
            "sk_id": "1",
            "sk_name": "Test SK",
            "eligible_voters": 100,
        }
    }
    fv2022_votes = {("test", "test ao"): {"A": 50}}
    personal_votes = {}   # No personal votes at all
    fv2022_kandidatdata = {
        "ok1": {
            "A": [{"id": "cand-x", "name": "Unknown Candidate", "ballot_position": 1}]
        }
    }

    wave_dir = tmp_path / "wave_26"
    write_fintaelling_wave(
        wave_dir=wave_dir,
        wave_index=26,
        ao_ids_in_wave=["701001"],
        hierarchy=hierarchy,
        fv2022_votes=fv2022_votes,
        kandidatdata=fv2022_kandidatdata,
        personal_votes=personal_votes,
    )

    vr_files = list((wave_dir / "valgresultater").glob("*.json"))
    vr = json.loads(vr_files[0].read_text())["Valgresultater"]
    party_a = next(p for p in vr["IndenforParti"] if p["PartiId"] == "A")
    assert party_a["Kandidater"][0]["Stemmer"] == 0
```

> **Note:** The second test imports from `build_fintaelling_wave` — this is intentionally wrong and will be fixed to `build_fv2022_scenario` once you paste it. Fix the import before running.

Run: `pytest tests/test_fv2022_build.py::test_write_fintaelling_wave_uses_real_votes -v`
Expected: FAIL (`write_fintaelling_wave` doesn't accept `personal_votes` yet).

- [ ] **Step 2: Update `write_fintaelling_wave`**

Replace the existing function signature and body. The current signature is:
```python
def write_fintaelling_wave(wave_dir, wave_index, ao_ids_in_wave, hierarchy, fv2022_votes, kandidatdata):
```

New function:

```python
def write_fintaelling_wave(
    wave_dir: Path,
    wave_index: int,
    ao_ids_in_wave: list[str],
    hierarchy: dict[str, dict],
    fv2022_votes: dict[tuple[str, str], dict[str, int]],
    kandidatdata: dict[str, dict[str, list[dict]]],
    personal_votes: dict[tuple[str, str], dict[str, dict[str, int]]],
    unmatched: list[tuple] | None = None,
) -> None:
    """Write one fintaelling wave: valgresultater with real personal votes."""
    wave_dir.mkdir(parents=True, exist_ok=True)
    t = WAVE_TIMES[wave_index]

    description = "Fintaelling — " + wave_description(wave_index, ao_ids_in_wave, hierarchy)
    (wave_dir / "_meta.json").write_text(json.dumps({
        "label": f"{t} — {description}",
        "time": t,
        "interval_s": float(WAVE_INTERVALS[wave_index]),
        "phase": "final",
    }, ensure_ascii=False, indent=2))

    vr_dir = wave_dir / "valgresultater"
    vr_dir.mkdir(exist_ok=True)

    for ao_id in ao_ids_in_wave:
        info = hierarchy[ao_id]
        ok_id = info["ok_id"]
        ok_name = info["ok_name"]
        ao_name = info["ao_name"]
        key = (normalize_ok_name(ok_name), normalize_ao_name(ao_name))
        ao_party_votes = fv2022_votes.get(key, {})
        ao_personal = personal_votes.get(key, {})

        party_data: dict[str, dict] = {}
        for party_id, total in ao_party_votes.items():
            candidates = kandidatdata.get(ok_id, {}).get(party_id, [])
            party_personal = ao_personal.get(party_id, {})
            kandidater = []
            for c in candidates:
                name_norm = normalize_name(c["name"])
                votes = party_personal.get(name_norm, 0)
                if name_norm not in party_personal and unmatched is not None:
                    unmatched.append((ok_name, ao_name, party_id, c["name"]))
                kandidater.append({"KandidatId": str(c["id"]), "Stemmer": votes})
            party_data[party_id] = {"total": total, "kandidater": kandidater}

        vr = build_valgresultater(
            ao_id=str(ao_id),
            optaellingstype="Fintaelling",
            party_data=party_data,
        )
        safe_ao_name = ao_name.replace("/", "-").replace(" ", "_")[:40]
        filename = f"valgresultater-Folketingsvalg-{safe_ao_name}-{ao_id}.json"
        (vr_dir / filename).write_text(json.dumps(vr, ensure_ascii=False, indent=2))
```

- [ ] **Step 3: Run the tests**

Run: `pytest tests/test_fv2022_build.py -v`
Expected: all pass including the two new tests.

- [ ] **Step 4: Commit**

```bash
git add scripts/build_fv2022_scenario.py tests/test_fv2022_build.py
git commit -m "feat: write_fintaelling_wave uses real personal votes"
```

---

### Task 6: Wire everything in `run()` and rebuild

Update `run()` to parse personal votes and FV2022 kandidat-data, pass them through, and rebuild the scenario.

**Files:**
- Modify: `scripts/build_fv2022_scenario.py`

- [ ] **Step 1: Update `run()`**

In the `run()` function, find the Phase 2 parsing block (around line 788) and update:

```python
    # Phase 2: Parse
    print("Phase 2: Parsing ...")
    geo_dir = CACHE_DIR / "fv2026" / "geografi"
    kd_dir = CACHE_DIR / "fv2022" / "kandidat-data"    # ← was fv2026
    csv_path = CACHE_DIR / "fv2022_results.csv"

    hierarchy = parse_geografi(geo_dir)
    kandidatdata = parse_kandidatdata(kd_dir)           # reuse existing parser
    fv2022_votes = parse_fv2022_csv(csv_path)
    personal_votes = parse_fv2022_personal_votes(csv_path)   # ← new
    id_mapping = build_id_mapping(hierarchy)
```

In Phase 4 (writing), update the `write_wave_00` call:

```python
    write_wave_00(OUTPUT_DIR, geo_dir, kd_dir, storkredse, opstillingskredse, all_aos, parties)
    #                                   ^^^^^ now points to fv2022 kandidat-data
```

Update the fintælling wave loop to pass `personal_votes` and `unmatched`:

```python
    unmatched: list[tuple] = []
    for wave_num in range(N_PRELIM_WAVES + 1, 33):
        ao_ids = final_by_wave.get(wave_num, [])
        if not ao_ids:
            continue
        wave_dir = OUTPUT_DIR / f"wave_{wave_num:02d}"
        write_fintaelling_wave(
            wave_dir, wave_num, ao_ids, matched_ao_ids,
            fv2022_votes, kandidatdata, personal_votes, unmatched,
        )
        print(f"  wave_{wave_num:02d}: fintaelling {len(ao_ids)} AOs")

    if unmatched:
        print(f"\nUnmatched candidates: {len(unmatched)} total")
        for ok, ao, party, name in unmatched[:10]:
            print(f"  {party} | {ok} / {ao} | {name}")
        if len(unmatched) > 10:
            print(f"  ... and {len(unmatched) - 10} more")
    else:
        print("\nAll candidates matched to personal votes.")
```

- [ ] **Step 2: Run the full test suite**

Run: `pytest tests/test_fv2022_build.py -v`
Expected: all pass.

- [ ] **Step 3: Run the full build**

```bash
python scripts/build_fv2022_scenario.py
```

Expected output:
- Phase 1: uses cached or downloads fv2022 kandidat-data
- Phase 2: parses without errors
- Phase 3: wave assignment as before
- Phase 4: writes 33 waves
- Unmatched summary printed (inspect — high unmatched count signals a name normalization or SFTP path issue)

If unmatched count is unexpectedly high (>50% of candidates):
- Check that `FV2022_SFTP_PATH` points to FV2022 data, not a different election
- Check that `parse_kandidatdata` is reading `kandidat-data/*.json` from FV2022, not FV2026
- Run `python -c "from pathlib import Path; import json; f=next((Path('scripts/.cache/fv2022/kandidat-data')).glob('*.json')); print(json.loads(f.read_text()).keys())"` to confirm the JSON structure

- [ ] **Step 4: Spot-check a wave file**

```bash
python -c "
import json
from pathlib import Path
files = sorted((Path('valg/scenarios/fv2022/wave_26/valgresultater')).glob('*.json'))
vr = json.loads(files[0].read_text())['Valgresultater']
party = vr['IndenforParti'][0]
print('Party:', party['PartiId'], 'Total:', party['Partistemmer'])
print('Candidates:', [(k['KandidatId'], k['Stemmer']) for k in party['Kandidater'][:3]])
"
```

Expected: candidates with non-zero, non-synthetic vote counts. Votes should NOT all follow a 35% pattern.

- [ ] **Step 5: Commit**

```bash
git add scripts/build_fv2022_scenario.py valg/scenarios/fv2022/
git commit -m "feat: FV2022 scenario uses real FV2022 candidates and personal votes"
```

---

## Completion Checklist

- [ ] All `pytest tests/test_fv2022_build.py` pass
- [ ] `distribute_candidate_votes` deleted from build script and tests
- [ ] `wave_00/kandidat-data/` contains FV2022 candidates (not FV2026)
- [ ] `wave_26..32/valgresultater/*.json` contain real personal vote counts
- [ ] Build prints an unmatched summary (even if count is 0)
- [ ] No FV2026 kandidat-data download in `download_all()`
