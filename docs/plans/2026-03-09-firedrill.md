# Firedrill Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** End-to-end firedrill that simulates a complete Danish election night using a fake fetcher, exercising the full pipeline — JSON generation → plugin parsing → processor → SQLite → CLI output.

**Architecture:** A `fake_fetcher.py` module generates valg.dk-format JSON files wave by wave (simulating SFTP data arriving). A `--fake --wave N` flag on `valg sync` uses the fake fetcher instead of SFTP. A `scripts/firedrill.py` orchestrator drives all waves and prints CLI output after each, so you can watch the numbers change in real time.

**Tech Stack:** Python 3.11+, existing `valg` package, `tests/synthetic/generator.py` for election structure, `rich` for firedrill output.

---

## Background: what the fake fetcher must produce

The plugins parse these file formats:

| Plugin | File pattern | Key JSON fields |
|--------|-------------|-----------------|
| `geografi` | `Storkreds.json` | list of `{Kode, Navn, AntalKredsmandater, ValgId}` |
| `kandidatdata_fv` | `kandidat-data-Folketingsvalg-*.json` | `{Valg: {Id, IndenforParti: [{Id, Kandidater: [{Id, Navn, Stemmeseddelplacering}]}], UdenforParti: {Kandidater:[]}}}` |
| `partistemmer` | `partistemmefordeling-*.json` | `{Valg: {OpstillingskredsId, Partier: [{PartiId, Stemmer}]}}` |
| `valgresultater_fv` | `valgresultater-Folketingsvalg-*.json` | `{Valgresultater: {AfstemningsomraadeId, Optaellingstype, IndenforParti: [{PartiId, Partistemmer, Kandidater:[{KandidatId, Stemmer}]}]}}` |
| `valgdeltagelse` | `valgdeltagelse-*.json` | `{Valg: {AfstemningsomraadeId, Valgdeltagelse: [{StemmeberettigedeVaelgere, AfgivneStemmer}]}}` |

**Gap:** `opstillingskredse`, `afstemningsomraader`, `parties`, and `elections` have no corresponding plugin — they are seeded directly via SQL in the setup step. This is documented and intentional for the firedrill.

## Firedrill waves

| Wave | Phase | Districts | Content written |
|------|-------|-----------|-----------------|
| 0 | Setup | — | `Storkreds.json` + `kandidat-data-*.json` + direct SQL seed |
| 1 | Preliminary | 25% | `partistemmefordeling-*.json` + `valgresultater-*` (preliminary) + `valgdeltagelse-*` |
| 2 | Preliminary | 50% | same, more districts |
| 3 | Preliminary | 100% | all districts |
| 4 | Fintælling | 50% | `valgresultater-*` (final, with candidates) |
| 5 | Fintælling | 100% | all districts fintælling |

---

## Task 1: fake_fetcher.py — JSON generators

**Files:**
- Create: `valg/fake_fetcher.py`
- Create: `tests/test_fake_fetcher.py`

### Step 1: Write failing tests

```python
# tests/test_fake_fetcher.py
import json
import pytest
from pathlib import Path
from valg.fake_fetcher import make_election, setup_db, write_wave
from valg.models import get_connection, init_db
from valg.plugins import load_plugins, find_plugin

@pytest.fixture
def election():
    return make_election()

@pytest.fixture
def db():
    conn = get_connection(":memory:")
    init_db(conn)
    load_plugins()
    return conn

def test_make_election_has_required_keys(election):
    for key in ("storkredse", "opstillingskredse", "afstemningsomraader", "parties", "candidates"):
        assert key in election

def test_setup_db_populates_geography(election, db):
    setup_db(db, election)
    count = db.execute("SELECT COUNT(*) FROM storkredse").fetchone()[0]
    assert count == len(election["storkredse"])

def test_setup_db_populates_parties(election, db):
    setup_db(db, election)
    count = db.execute("SELECT COUNT(*) FROM parties").fetchone()[0]
    assert count == len(election["parties"])

def test_write_wave0_produces_storkreds_json(election, tmp_path):
    write_wave(tmp_path, election, wave=0)
    assert (tmp_path / "Storkreds.json").exists()

def test_write_wave0_storkreds_parseable_by_plugin(election, tmp_path):
    write_wave(tmp_path, election, wave=0)
    data = json.loads((tmp_path / "Storkreds.json").read_text())
    plugin = find_plugin("Storkreds.json")
    rows = plugin.parse(data, "2024-11-05T21:00:00")
    assert len(rows) == len(election["storkredse"])

def test_write_wave1_produces_partistemmer_files(election, tmp_path):
    write_wave(tmp_path, election, wave=1)
    files = list(tmp_path.glob("partistemmefordeling-*.json"))
    assert len(files) > 0

def test_write_wave1_partistemmer_parseable_by_plugin(election, tmp_path):
    write_wave(tmp_path, election, wave=1)
    plugin = find_plugin("partistemmefordeling-OK1.json")
    for f in tmp_path.glob("partistemmefordeling-*.json"):
        data = json.loads(f.read_text())
        rows = plugin.parse(data, "2024-11-05T21:00:00")
        assert len(rows) > 0

def test_write_wave1_valgresultater_parseable_by_plugin(election, tmp_path):
    write_wave(tmp_path, election, wave=1)
    plugin = find_plugin("valgresultater-Folketingsvalg-AO1.json")
    for f in tmp_path.glob("valgresultater-Folketingsvalg-*.json"):
        data = json.loads(f.read_text())
        rows = plugin.parse(data, "2024-11-05T21:00:00")
        assert all(r["count_type"] == "preliminary" for r in rows)

def test_write_wave4_produces_final_results(election, tmp_path):
    write_wave(tmp_path, election, wave=4)
    plugin = find_plugin("valgresultater-Folketingsvalg-AO1.json")
    for f in tmp_path.glob("valgresultater-Folketingsvalg-*.json"):
        data = json.loads(f.read_text())
        rows = plugin.parse(data, "2024-11-06T10:00:00")
        assert all(r["count_type"] == "final" for r in rows)
        # Final rows should have candidate IDs
        candidate_rows = [r for r in rows if r["candidate_id"] is not None]
        assert len(candidate_rows) > 0

def test_wave3_covers_all_districts(election, tmp_path):
    write_wave(tmp_path, election, wave=3)
    n_ao = len(election["afstemningsomraader"])
    files = list(tmp_path.glob("valgresultater-Folketingsvalg-*.json"))
    assert len(files) == n_ao
```

### Step 2: Run to confirm failure

```bash
.venv/bin/pytest tests/test_fake_fetcher.py -v
```

Expected: `ImportError: cannot import name 'make_election' from 'valg.fake_fetcher'`

### Step 3: Implement valg/fake_fetcher.py

```python
# valg/fake_fetcher.py
"""
Fake fetcher for firedrill testing.

Generates valg.dk-format JSON files from synthetic election data, wave by wave.
Bypasses SFTP entirely — writes directly to a local data directory.

Wave schedule:
  0 — setup: Storkreds.json + kandidat-data (geography/candidates)
  1 — 25% districts preliminary
  2 — 50% districts preliminary
  3 — 100% districts preliminary
  4 — 50% districts fintælling
  5 — 100% districts fintælling
"""
import json
import random
from pathlib import Path

ELECTION_ID = "FV2024"
SEED = 42
WAVE_FRACTIONS = {1: 0.25, 2: 0.50, 3: 1.0, 4: 0.50, 5: 1.0}


def make_election(
    n_parties: int = 6,
    n_storkredse: int = 3,
    n_districts: int = 30,
    seed: int = SEED,
) -> dict:
    """Generate a small but realistic synthetic election structure."""
    from tests.synthetic.generator import generate_election
    return generate_election(
        n_parties=n_parties,
        n_storkredse=n_storkredse,
        n_districts=n_districts,
        seed=seed,
    )


def setup_db(conn, election: dict) -> None:
    """
    Seed geography, parties, and candidates directly into the DB.

    These entities have no plugin yet (no JSON file format documented),
    so we insert them via SQL as a setup step.
    """
    election_id = ELECTION_ID
    conn.execute(
        "INSERT OR REPLACE INTO elections (id, name) VALUES (?, ?)",
        (election_id, "Syntetisk Valg 2024"),
    )
    for sk in election["storkredse"]:
        conn.execute(
            "INSERT OR REPLACE INTO storkredse (id, name, election_id, n_kredsmandater) VALUES (?,?,?,?)",
            (sk["id"], sk["name"], election_id, sk["n_kredsmandater"]),
        )
    for ok in election["opstillingskredse"]:
        conn.execute(
            "INSERT OR REPLACE INTO opstillingskredse (id, name, storkreds_id) VALUES (?,?,?)",
            (ok["id"], ok["name"], ok["storkreds_id"]),
        )
    for ao in election["afstemningsomraader"]:
        conn.execute(
            "INSERT OR REPLACE INTO afstemningsomraader (id, name, opstillingskreds_id, municipality_name, eligible_voters) VALUES (?,?,?,?,?)",
            (ao["id"], ao["name"], ao["opstillingskreds_id"], ao["municipality_name"], ao["eligible_voters"]),
        )
    for p in election["parties"]:
        conn.execute(
            "INSERT OR REPLACE INTO parties (id, letter, name, election_id) VALUES (?,?,?,?)",
            (p["id"], p["letter"], p["name"], election_id),
        )
    for c in election["candidates"]:
        conn.execute(
            "INSERT OR REPLACE INTO candidates (id, name, party_id, opstillingskreds_id, ballot_position) VALUES (?,?,?,?,?)",
            (c["id"], c["name"], c["party_id"], c["opstillingskreds_id"], c["ballot_position"]),
        )
    conn.commit()


def write_wave(data_dir: Path, election: dict, wave: int) -> list[Path]:
    """
    Write JSON files for the given wave to data_dir.
    Returns list of written paths.
    """
    data_dir = Path(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    rng = random.Random(SEED + wave)

    written = []
    if wave == 0:
        written += _write_storkreds(data_dir, election)
        written += _write_kandidatdata(data_dir, election)
    elif wave in (1, 2, 3):
        fraction = WAVE_FRACTIONS[wave]
        districts = _select_districts(election["afstemningsomraader"], fraction, rng)
        written += _write_partistemmer(data_dir, election, districts, rng)
        written += _write_valgresultater_preliminary(data_dir, election, districts, rng)
        written += _write_valgdeltagelse(data_dir, election, districts, rng)
    elif wave in (4, 5):
        fraction = WAVE_FRACTIONS[wave]
        districts = _select_districts(election["afstemningsomraader"], fraction, rng)
        written += _write_valgresultater_final(data_dir, election, districts, rng)
    return written


def _select_districts(all_districts: list, fraction: float, rng: random.Random) -> list:
    n = max(1, int(len(all_districts) * fraction))
    return sorted(all_districts, key=lambda d: d["id"])[:n]


def _write(path: Path, data) -> Path:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2))
    return path


def _write_storkreds(data_dir: Path, election: dict) -> list[Path]:
    data = [
        {"Kode": sk["id"], "Navn": sk["name"],
         "AntalKredsmandater": sk["n_kredsmandater"], "ValgId": ELECTION_ID}
        for sk in election["storkredse"]
    ]
    return [_write(data_dir / "Storkreds.json", data)]


def _write_kandidatdata(data_dir: Path, election: dict) -> list[Path]:
    by_party: dict[str, list] = {}
    for c in election["candidates"]:
        by_party.setdefault(c["party_id"], []).append(c)

    data = {
        "Valg": {
            "Id": ELECTION_ID,
            "IndenforParti": [
                {
                    "Id": party_id,
                    "Kandidater": [
                        {"Id": c["id"], "Navn": c["name"],
                         "Stemmeseddelplacering": c.get("ballot_position", 1)}
                        for c in candidates
                    ],
                }
                for party_id, candidates in by_party.items()
            ],
            "UdenforParti": {"Kandidater": []},
        }
    }
    filename = f"kandidat-data-Folketingsvalg-{ELECTION_ID}.json"
    return [_write(data_dir / filename, data)]


def _write_partistemmer(data_dir: Path, election: dict, districts: list, rng: random.Random) -> list[Path]:
    # Group districts by opstillingskreds
    ok_districts: dict[str, list] = {}
    for ao in districts:
        ok_districts.setdefault(ao["opstillingskreds_id"], []).append(ao)

    written = []
    for ok_id, aos in ok_districts.items():
        data = {
            "Valg": {
                "OpstillingskredsId": ok_id,
                "Partier": [
                    {"PartiId": p["id"], "Stemmer": rng.randint(100, 5000)}
                    for p in election["parties"]
                ],
            }
        }
        written.append(_write(data_dir / f"partistemmefordeling-{ok_id}.json", data))
    return written


def _write_valgresultater_preliminary(data_dir: Path, election: dict, districts: list, rng: random.Random) -> list[Path]:
    written = []
    for ao in districts:
        data = {
            "Valgresultater": {
                "AfstemningsomraadeId": ao["id"],
                "Optaellingstype": "Foreløbig",
                "IndenforParti": [
                    {
                        "PartiId": p["id"],
                        "Partistemmer": rng.randint(50, 1000),
                        "Kandidater": [],
                    }
                    for p in election["parties"]
                ],
                "KandidaterUdenforParti": [],
            }
        }
        filename = f"valgresultater-Folketingsvalg-{ao['id']}.json"
        written.append(_write(data_dir / filename, data))
    return written


def _write_valgresultater_final(data_dir: Path, election: dict, districts: list, rng: random.Random) -> list[Path]:
    # Build lookup: (opstillingskreds_id, party_id) -> candidates
    ok_party_cands: dict[tuple, list] = {}
    for c in election["candidates"]:
        ok_party_cands.setdefault((c["opstillingskreds_id"], c["party_id"]), []).append(c)

    written = []
    for ao in districts:
        ok_id = ao["opstillingskreds_id"]
        data = {
            "Valgresultater": {
                "AfstemningsomraadeId": ao["id"],
                "Optaellingstype": "Fintælling",
                "IndenforParti": [
                    {
                        "PartiId": p["id"],
                        "Partistemmer": rng.randint(50, 1000),
                        "Kandidater": [
                            {"KandidatId": c["id"], "Stemmer": rng.randint(5, 300)}
                            for c in ok_party_cands.get((ok_id, p["id"]), [])
                        ],
                    }
                    for p in election["parties"]
                ],
                "KandidaterUdenforParti": [],
            }
        }
        filename = f"valgresultater-Folketingsvalg-{ao['id']}.json"
        written.append(_write(data_dir / filename, data))
    return written


def _write_valgdeltagelse(data_dir: Path, election: dict, districts: list, rng: random.Random) -> list[Path]:
    written = []
    for ao in districts:
        eligible = ao.get("eligible_voters", 3000)
        cast = rng.randint(int(eligible * 0.6), eligible)
        data = {
            "Valg": {
                "AfstemningsomraadeId": ao["id"],
                "Valgdeltagelse": [
                    {
                        "StemmeberettigedeVaelgere": eligible,
                        "AfgivneStemmer": cast,
                    }
                ],
            }
        }
        written.append(_write(data_dir / f"valgdeltagelse-{ao['id']}.json", data))
    return written
```

### Step 4: Run tests — confirm all pass

```bash
.venv/bin/pytest tests/test_fake_fetcher.py -v
```

Expected: 11 PASSED

### Step 5: Run full suite — no regressions

```bash
.venv/bin/pytest -q
```

Expected: 146 passed

### Step 6: Commit

```bash
git add valg/fake_fetcher.py tests/test_fake_fetcher.py
git commit -m "feat: fake fetcher — synthetic valg.dk JSON generator for firedrill"
```

---

## Task 2: `valg sync --fake` CLI flag

**Files:**
- Modify: `valg/cli.py` (`cmd_sync` and `build_parser`)

### Step 1: Write failing test

Add to `tests/test_cli.py`:

```python
def test_sync_fake_wave0_populates_storkredse(tmp_path):
    import subprocess, sys
    db = tmp_path / "test.db"
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    result = subprocess.run(
        [sys.executable, "-m", "valg", "--db", str(db),
         "sync", "--fake", "--wave", "0", "--data-dir", str(data_dir)],
        capture_output=True, text=True,
        cwd=str(Path(__file__).parent.parent),
    )
    assert result.returncode == 0, result.stderr
    from valg.models import get_connection
    conn = get_connection(db)
    count = conn.execute("SELECT COUNT(*) FROM storkredse").fetchone()[0]
    assert count > 0

def test_sync_fake_wave1_populates_party_votes(tmp_path):
    import subprocess, sys
    db = tmp_path / "test.db"
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    for wave in (0, 1):
        subprocess.run(
            [sys.executable, "-m", "valg", "--db", str(db),
             "sync", "--fake", "--wave", str(wave), "--data-dir", str(data_dir)],
            capture_output=True, text=True,
            cwd=str(Path(__file__).parent.parent),
            check=True,
        )
    from valg.models import get_connection
    conn = get_connection(db)
    count = conn.execute("SELECT COUNT(*) FROM party_votes").fetchone()[0]
    assert count > 0
```

### Step 2: Run to confirm failure

```bash
.venv/bin/pytest tests/test_cli.py::test_sync_fake_wave0_populates_storkredse -v
```

Expected: FAIL — `--fake` not a recognised argument.

### Step 3: Modify cli.py

In `build_parser`, add to the `sync` subparser:

```python
sync_p.add_argument("--fake", action="store_true",
                    help="Use fake fetcher instead of SFTP (firedrill mode)")
sync_p.add_argument("--wave", type=int, default=0,
                    help="Fake fetcher wave index (0=setup, 1-3=preliminary, 4-5=final)")
sync_p.add_argument("--data-dir", type=Path, default=None,
                    help="Override data directory (used with --fake)")
```

Replace `cmd_sync` with:

```python
def cmd_sync(conn, args):
    from valg.processor import process_directory
    from valg.plugins import load_plugins
    from datetime import datetime, timezone

    load_plugins()
    snapshot_at = datetime.now(timezone.utc).isoformat()

    if getattr(args, "fake", False):
        from valg.fake_fetcher import make_election, setup_db, write_wave
        import tempfile, os

        data_dir = args.data_dir or Path(tempfile.mkdtemp(prefix="valg-fake-"))
        election = make_election()

        if args.wave == 0:
            setup_db(conn, election)

        written = write_wave(data_dir, election, args.wave)
        console.print(f"[dim]Fake wave {args.wave}: {len(written)} files written to {data_dir}[/dim]")
        total = process_directory(conn, data_dir, snapshot_at=snapshot_at)
        console.print(f"Processed {total} rows (wave {args.wave})")
        return

    from valg.fetcher import get_sftp_client, sync_election_folder, commit_data_repo
    import os

    data_repo = Path(os.getenv("VALG_DATA_REPO", "../valg-data"))
    election_folder = args.election_folder

    console.print(f"Syncing {election_folder}...")
    ssh, sftp = get_sftp_client()
    try:
        downloaded = sync_election_folder(sftp, election_folder, data_repo)
        console.print(f"Downloaded {downloaded} files")
    finally:
        sftp.close()
        ssh.close()

    total = process_directory(conn, data_repo, snapshot_at=snapshot_at)
    console.print(f"Processed {total} rows")
    commit_data_repo(data_repo)
```

### Step 4: Run tests — confirm pass

```bash
.venv/bin/pytest tests/test_cli.py -v -k "fake"
```

Expected: 2 PASSED

### Step 5: Full suite

```bash
.venv/bin/pytest -q
```

Expected: 148 passed

### Step 6: Commit

```bash
git add valg/cli.py tests/test_cli.py
git commit -m "feat: valg sync --fake --wave N for firedrill mode"
```

---

## Task 3: scripts/firedrill.py — orchestrator

**Files:**
- Create: `scripts/firedrill.py`

No automated tests for this script (it's an interactive runner). Manual verification below.

### Step 1: Write scripts/firedrill.py

```python
#!/usr/bin/env python3
"""
Firedrill: simulates a complete election night using synthetic data.

Usage:
    python scripts/firedrill.py                  # runs all 6 waves
    python scripts/firedrill.py --wave 0 1 2     # specific waves only
    python scripts/firedrill.py --pause          # pause between waves
    python scripts/firedrill.py --db /tmp/my.db  # custom DB path
"""
import argparse
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).parent.parent
DB_DEFAULT = Path(tempfile.gettempdir()) / "valg-firedrill.db"
DATA_DIR = Path(tempfile.gettempdir()) / "valg-firedrill-data"

WAVE_LABELS = {
    0: "Wave 0 — Setup (geography, parties, candidates)",
    1: "Wave 1 — 25% districts reporting (preliminary)",
    2: "Wave 2 — 50% districts reporting (preliminary)",
    3: "Wave 3 — 100% districts reporting (preliminary)",
    4: "Wave 4 — 50% districts fintælling",
    5: "Wave 5 — 100% districts fintælling",
}

COMMANDS_AFTER_WAVE = {
    0: [],
    1: ["status", "flip"],
    2: ["status", "flip"],
    3: ["status", "flip", "party A"],
    4: ["status", "candidate Kandidat"],
    5: ["status", "flip", "feed"],
}


def run(cmd: list[str], db: Path) -> str:
    result = subprocess.run(
        [sys.executable, "-m", "valg", "--db", str(db)] + cmd,
        capture_output=True, text=True, cwd=str(ROOT),
    )
    return result.stdout + result.stderr


def run_wave(wave: int, db: Path) -> None:
    print(f"\n{'='*60}")
    print(f"  {WAVE_LABELS[wave]}")
    print(f"{'='*60}")

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        [sys.executable, "-m", "valg", "--db", str(db),
         "sync", "--fake", "--wave", str(wave),
         "--data-dir", str(DATA_DIR)],
        capture_output=True, text=True, cwd=str(ROOT),
    )
    if result.returncode != 0:
        print(f"ERROR in sync: {result.stderr}")
        return
    print(result.stdout.strip())

    for cmd_str in COMMANDS_AFTER_WAVE.get(wave, []):
        print(f"\n--- valg {cmd_str} ---")
        print(run(cmd_str.split(), db))


def main():
    p = argparse.ArgumentParser(description="valg firedrill")
    p.add_argument("--wave", type=int, nargs="+", default=list(range(6)),
                   help="Which waves to run (default: 0-5)")
    p.add_argument("--pause", action="store_true",
                   help="Pause between waves for manual inspection")
    p.add_argument("--db", type=Path, default=DB_DEFAULT,
                   help=f"DB path (default: {DB_DEFAULT})")
    p.add_argument("--fresh", action="store_true",
                   help="Delete DB before starting")
    args = p.parse_args()

    if args.fresh and args.db.exists():
        args.db.unlink()
        print(f"Deleted {args.db}")

    print(f"Firedrill DB: {args.db}")
    print(f"Data dir:     {DATA_DIR}")

    for wave in sorted(args.wave):
        run_wave(wave, args.db)
        if args.pause and wave < max(args.wave):
            input("\nPress Enter for next wave...")

    print(f"\n{'='*60}")
    print("  Firedrill complete.")
    print(f"  DB: {args.db}")
    print(f"  Run: python -m valg --db {args.db} status")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
```

### Step 2: Manual verification

Run the full firedrill:

```bash
python scripts/firedrill.py --fresh
```

Expected output (abbreviated):
```
============================================================
  Wave 0 — Setup (geography, parties, candidates)
============================================================
Fake wave 0: 2 files written to /tmp/valg-firedrill-data
Processed N rows (wave 0)

============================================================
  Wave 1 — 25% districts reporting (preliminary)
============================================================
Fake wave 1: M files written to /tmp/valg-firedrill-data
Processed N rows (wave 1)

--- valg status ---
Districts: 8/30 foreløbig, 0/30 fintælling
┏━━━━━━━┳━━━━━━━━━━━┳━━━━━━━┓
┃ Party ┃ Votes     ┃ Seats ┃
...

--- valg flip ---
...
```

Run a single wave then inspect:

```bash
# Reset, run only through wave 2, then poke around manually
python scripts/firedrill.py --fresh --wave 0 1 2
python -m valg --db /tmp/valg-firedrill.db status
python -m valg --db /tmp/valg-firedrill.db flip
python -m valg --db /tmp/valg-firedrill.db party A
```

After wave 5 (fintælling complete):

```bash
python scripts/firedrill.py --wave 4 5
python -m valg --db /tmp/valg-firedrill.db candidate Kandidat
python -m valg --db /tmp/valg-firedrill.db feed
```

### Step 3: Commit

```bash
git add scripts/firedrill.py
git commit -m "feat: firedrill script — simulates election night wave by wave"
```

---

## Task 4: Push

```bash
git push
```

Verify on GitHub that all commits are present. The firedrill is now runnable locally and testable on any machine with:

```bash
pip install -e ".[dev]"
python scripts/firedrill.py --fresh
```
